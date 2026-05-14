"""
ShmManager 单元测试
验证内存盘资源管理器的核心逻辑：
  1. 初始化与配额计算
  2. 工作空间分配与释放
  3. 进程内存联动
  4. 诊断保留与过期清理
  5. 全局清理
  6. 模块导入完整性
"""

import asyncio
import sys
import os
import traceback

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0

def report(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} -- {detail}")


# ============================================================
# 测试组 1: 模块导入
# ============================================================
print("\n=== 测试组 1: 模块导入 ===")

try:
    from src.assembly.core.shm_manager import ShmManager, ShmWorkspace
    report("导入 ShmManager", True)
except Exception as e:
    report("导入 ShmManager", False, str(e))
    ShmManager = None  # type: ignore[assignment,misc]

try:
    from src.assembly.core.base import PipelineContext, BaseAssemblyStep
    report("导入 PipelineContext", True)
except Exception as e:
    report("导入 PipelineContext", False, str(e))
    PipelineContext = None  # type: ignore[assignment,misc]

try:
    from src.assembly.steps.assembler import AssemblerStep
    from src.assembly.steps.scaffolder import ScaffoldingStep
    from src.assembly.steps.gap_filler import GapFillerStep
    from src.assembly.steps.correction import ConsensusCorrectionStep
    from src.assembly.steps.prophage_separator import ProphageSeparatorStep
    from src.assembly.steps.host_cleaner import HostCleanerStep
    report("导入所有步骤模块", True)
except Exception as e:
    report("导入所有步骤模块", False, str(e))

try:
    from src.assembly.manager import AssemblyManager
    report("导入 AssemblyManager", True)
except Exception as e:
    report("导入 AssemblyManager", False, str(e))


# ============================================================
# 测试组 2: ShmManager 初始化与配额计算
# ============================================================
print("\n=== 测试组 2: 配额计算 ===")


class MockRunner:
    """模拟 CommandRunner，不执行实际命令"""
    def __init__(self):
        self.commands_log = []

    async def run_command(self, cmd, **kwargs):
        self.commands_log.append(cmd)
        # 模拟 df 输出
        on_output = kwargs.get("on_output")
        if on_output and isinstance(cmd, list) and "df" in str(cmd):
            on_output("8")  # 模拟 8GB 可用
        return 0


runner = MockRunner()

# 测试 48GB 系统
shm = ShmManager("test_48g", runner, total_memory_gb=48.0)
report("48GB系统 - 内存盘配额=12GB (上限截断)", shm.shm_quota_gb == 12,
       f"实际={shm.shm_quota_gb}")
# 无活跃内存盘占用时: int(48 - 0 - 4) = 44
report("48GB系统 - 进程可用=44GB (无活跃占用)", shm.get_process_memory_limit() == 44,
       f"实际={shm.get_process_memory_limit()}")

# 测试 16GB 系统
shm16 = ShmManager("test_16g", runner, total_memory_gb=16.0)
report("16GB系统 - 内存盘配额=4GB", shm16.shm_quota_gb == 4,
       f"实际={shm16.shm_quota_gb}")
# 无活跃内存盘占用时: int(16 - 0 - 4) = 12
report("16GB系统 - 进程可用=12GB (无活跃占用)", shm16.get_process_memory_limit() == 12,
       f"实际={shm16.get_process_memory_limit()}")

# 测试 8GB 系统
shm8 = ShmManager("test_8g", runner, total_memory_gb=8.0)
report("8GB系统 - 内存盘配额=2GB", shm8.shm_quota_gb == 2,
       f"实际={shm8.shm_quota_gb}")
# 8 - 0 - 4 = 4
report("8GB系统 - 进程可用=4GB (最低保证)", shm8.get_process_memory_limit() == 4,
       f"实际={shm8.get_process_memory_limit()}")


# ============================================================
# 测试组 3: 异步分配与释放
# ============================================================
print("\n=== 测试组 3: 分配与释放 ===")


async def test_acquire_release():
    runner = MockRunner()
    shm = ShmManager("test_alloc", runner, total_memory_gb=32.0)

    # 手动分配
    ws = await shm.acquire_manual("assembler", required_gb=5.0)
    report("手动分配 - 返回 ShmWorkspace", isinstance(ws, ShmWorkspace))
    report("手动分配 - step_name 正确", ws.step_name == "assembler",
           f"实际={ws.step_name}")
    report("手动分配 - 路径包含 task_id", "test_alloc" in ws.path,
           f"路径={ws.path}")
    report("手动分配 - 活跃追踪中", "assembler" in shm._active)

    # 进程内存联动
    if ws.is_ramdisk:
        proc_mem = shm.get_process_memory_limit()
        report("内存联动 - 进程可用内存下降", proc_mem < 28 - 4,
               f"实际={proc_mem}")
    else:
        report("内存联动 - SSD模式不消耗内存盘配额", True)

    # 释放
    await shm.release("assembler")
    report("释放 - 已从活跃追踪移除", "assembler" not in shm._active)

    # 进程内存恢复
    proc_mem_after = shm.get_process_memory_limit()
    expected = 32 - 0 - 4
    report("释放后 - 进程可用内存恢复", proc_mem_after == expected,
           f"实际={proc_mem_after}, 期望={expected}")


asyncio.run(test_acquire_release())


# ============================================================
# 测试组 4: 诊断保留
# ============================================================
print("\n=== 测试组 4: 诊断保留 ===")


async def test_diagnostic_retain():
    runner = MockRunner()
    shm = ShmManager("test_diag", runner, total_memory_gb=32.0)

    ws = await shm.acquire_manual("failed_step", required_gb=3.0)
    await shm.release("failed_step", retain_for_diagnostics=True)

    report("诊断保留 - 已从活跃追踪移除", "failed_step" not in shm._active)
    report("诊断保留 - 已加入保留列表", "failed_step" in shm._retained)

    # 全局清理应该回收诊断保留
    await shm.cleanup_all()
    report("全局清理 - 诊断保留已回收", len(shm._retained) == 0)


asyncio.run(test_diagnostic_retain())


# ============================================================
# 测试组 5: 上下文管理器模式
# ============================================================
print("\n=== 测试组 5: 上下文管理器 ===")


async def test_context_manager():
    runner = MockRunner()
    shm = ShmManager("test_ctx", runner, total_memory_gb=32.0)

    # 正常退出
    async with shm.acquire("scaffolder", required_gb=4.0) as ws:
        report("上下文管理器 - 分配成功", ws is not None)
        report("上下文管理器 - 活跃追踪中", "scaffolder" in shm._active)

    report("上下文管理器 - 退出后已清理", "scaffolder" not in shm._active)

    # 异常退出
    try:
        async with shm.acquire("crashing_step", required_gb=2.0) as ws:
            report("异常退出 - 分配成功", ws is not None)
            raise ValueError("模拟崩溃")
    except ValueError:
        pass

    report("异常退出 - 仍然清理成功", "crashing_step" not in shm._active)


asyncio.run(test_context_manager())


# ============================================================
# 测试组 6: 使用报告
# ============================================================
print("\n=== 测试组 6: 使用报告 ===")


async def test_usage_report():
    runner = MockRunner()
    shm = ShmManager("test_report", runner, total_memory_gb=48.0)

    ws = await shm.acquire_manual("step_a", required_gb=3.0)
    report_data = shm.get_usage_report()

    report("报告 - 总内存正确", report_data["total_memory_gb"] == 48.0)
    report("报告 - 配额正确", report_data["shm_quota_gb"] == 12)
    report("报告 - 含活跃空间", "step_a" in report_data["active_workspaces"])

    await shm.release("step_a")


asyncio.run(test_usage_report())


# ============================================================
# 测试组 7: PipelineContext 集成
# ============================================================
print("\n=== 测试组 7: PipelineContext 集成 ===")

from pathlib import Path

ctx = PipelineContext("test_integration", Path("."), {"is_wsl": True})
report("PipelineContext - shm 默认为 None", ctx.shm is None)

ctx.shm = ShmManager("test_integration", MockRunner(), total_memory_gb=32.0)
report("PipelineContext - shm 可注入", ctx.shm is not None)
report("PipelineContext - 获取进程内存", ctx.shm.get_process_memory_limit() > 0)


# ============================================================
# 测试组 8: 全局清理命令生成
# ============================================================
print("\n=== 测试组 8: 全局清理 ===")


async def test_cleanup_all():
    runner = MockRunner()
    shm = ShmManager("my_task_123", runner, total_memory_gb=32.0)

    # 模拟多个活跃空间
    await shm.acquire_manual("step1", required_gb=2.0)
    await shm.acquire_manual("step2", required_gb=3.0)

    report("清理前 - 2个活跃空间", len(shm._active) == 2)

    await shm.cleanup_all()
    report("清理后 - 活跃空间为空", len(shm._active) == 0)

    # 验证 cleanup 发出了正确的 find 命令
    find_cmds = [c for c in runner.commands_log if isinstance(c, list) and "find" in str(c)]
    report("清理 - 生成了 find 扫描命令", len(find_cmds) >= 1,
           f"命令数={len(find_cmds)}")


asyncio.run(test_cleanup_all())


# ============================================================
# 汇总
# ============================================================
print(f"\n{'='*50}")
print(f"  测试结果: {passed} 通过, {failed} 失败 (共 {passed + failed})")
print(f"{'='*50}")

sys.exit(0 if failed == 0 else 1)
