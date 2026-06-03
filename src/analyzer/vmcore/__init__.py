"""vmcore 解析模块

负责基于 drgn 等工具从 vmcore 文件中提取内核对象和特征。
"""

from ..models import CrashFeature


def extract_features_from_vmcore(vmcore_path: str, vmlinux_path: str) -> CrashFeature:
    """从 vmcore 中提取特征"""
    feature = CrashFeature()
    feature.extra_info["vmcore_path"] = vmcore_path
    feature.extra_info["vmlinux_path"] = vmlinux_path
    
    try:
        # 动态导入 drgn，避免静态检查报错
        import importlib
        drgn = importlib.import_module("drgn")
        # linux_helpers = importlib.import_module("drgn.helpers.linux")
        
        # 实际实现中这里会使用 drgn 加载 vmcore
        # prog = drgn.program_from_core(vmcore_path, vmlinux_path)
        
        # 示例：提取内核版本
        # feature.kernel_version = prog['linux_banner'].string_().decode()
        
        # 示例：提取 Call Trace (需要针对具体 panic 线程)
        # feature.call_trace = [...] 
        
        feature.extra_info["source"] = "vmcore"
        feature.extra_info["drgn_version"] = getattr(drgn, "__version__", "unknown")
        
    except ImportError:
        # 如果没有 drgn，记录错误或返回基本信息
        feature.extra_info["error"] = "drgn not installed"
        feature.extra_info["source"] = "vmcore"
    except Exception as e:
        feature.extra_info["error"] = str(e)
        feature.extra_info["source"] = "vmcore"
        
    return feature


def analyze_vmcore(vmcore_path: str, vmlinux_path: str = "") -> CrashFeature:
    """分析 vmcore 文件的主入口"""
    return extract_features_from_vmcore(vmcore_path, vmlinux_path)
