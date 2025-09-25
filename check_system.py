#!/usr/bin/env python3
"""
系统完整性检查
"""
import sys
import os
sys.path.append(os.path.dirname(__file__))

def check_imports():
    """检查所有关键模块是否能正常导入"""
    print("🔍 检查模块导入...")

    try:
        # 检查Function Call系统
        from function_calls.spec import FunctionSpec, FunctionResult
        from function_calls.registry import register_function, list_functions
        from function_calls.router import FunctionCallRouter
        from function_calls.llm import FunctionCallLLM
        import function_calls.init_handlers
        print("✅ Function Call核心模块导入成功")

        # 检查处理器
        from function_calls.handlers import (
            handle_reminder_set,
            handle_reminder_list,
            handle_reminder_delete,
            handle_perplexity_search,
            handle_summary,
        )
        print("✅ 核心处理器导入成功")

        # 检查参数模型
        from function_calls.models import (
            WeatherArgs, NewsArgs, HelpArgs, ReminderArgs,
            PerplexityArgs, SummaryArgs, ClearMessagesArgs
        )
        print("✅ 参数模型导入成功")

        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False

def check_function_registration():
    """检查函数注册是否正常"""
    print("\n🔍 检查函数注册...")

    try:
        from function_calls.registry import list_functions
        functions = list_functions()

        expected_count = 5
        if len(functions) != expected_count:
            print(f"⚠️ 函数数量异常: 期望{expected_count}个，实际{len(functions)}个")
            return False

        required_functions = [
            'reminder_set', 'reminder_list', 'reminder_delete',
            'perplexity_search', 'summary'
        ]

        missing_functions = []
        for func_name in required_functions:
            if func_name not in functions:
                missing_functions.append(func_name)

        if missing_functions:
            print(f"❌ 缺少函数: {missing_functions}")
            return False

        print("✅ 所有必需函数都已正确注册")
        return True

    except Exception as e:
        print(f"❌ 函数注册检查失败: {e}")
        return False

def check_router_initialization():
    """检查路由器初始化"""
    print("\n🔍 检查路由器初始化...")

    try:
        from function_calls.router import FunctionCallRouter
        router = FunctionCallRouter()
        print("✅ FunctionCallRouter初始化成功")

        print("✅ FunctionCallRouter 初始化成功")
        return True

    except Exception as e:
        print(f"❌ 路由器初始化失败: {e}")
        return False

def check_config_compatibility():
    """检查配置兼容性"""
    print("\n🔍 检查配置文件...")

    try:
        # 检查模板文件是否包含新配置
        with open('config.yaml.template', 'r', encoding='utf-8') as f:
            content = f.read()

        if 'function_call_router:' not in content:
            print("❌ config.yaml.template缺少function_call_router配置")
            return False

        print("✅ 配置文件包含Function Call配置")
        return True

    except Exception as e:
        print(f"❌ 配置检查失败: {e}")
        return False

def main():
    print("🚀 Function Call系统完整性检查\n")

    checks = [
        ("模块导入", check_imports),
        ("函数注册", check_function_registration),
        ("路由器初始化", check_router_initialization),
        ("配置兼容性", check_config_compatibility)
    ]

    passed = 0
    total = len(checks)

    for name, check_func in checks:
        if check_func():
            passed += 1
        else:
            print(f"❌ {name}检查失败")

    print(f"\n📊 检查结果: {passed}/{total} 通过")

    if passed == total:
        print("🎉 Function Call系统完整性检查全部通过！系统已准备就绪。")
        return 0
    else:
        print("⚠️ 部分检查失败，请检查上述错误信息。")
        return 1

if __name__ == "__main__":
    sys.exit(main())
