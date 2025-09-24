"""
函数注册中心
"""
import logging
from typing import Dict, Any, get_type_hints
from pydantic import BaseModel

from .spec import FunctionSpec

logger = logging.getLogger(__name__)

# 全局函数注册表
FUNCTION_REGISTRY: Dict[str, FunctionSpec] = {}


def register_function(spec: FunctionSpec) -> None:
    """注册函数到全局注册表"""
    if spec.name in FUNCTION_REGISTRY:
        raise ValueError(f"重复的函数名: {spec.name}")
    FUNCTION_REGISTRY[spec.name] = spec
    logger.info(f"注册函数: {spec.name} - {spec.description}")


def get_function(name: str) -> FunctionSpec:
    """获取指定名称的函数规格"""
    if name not in FUNCTION_REGISTRY:
        raise ValueError(f"未找到函数: {name}")
    return FUNCTION_REGISTRY[name]


def list_functions() -> Dict[str, FunctionSpec]:
    """获取所有已注册的函数"""
    return FUNCTION_REGISTRY.copy()


def build_schema_from_model(model_class) -> Dict[str, Any]:
    """从 Pydantic 模型构建 JSON Schema"""
    if issubclass(model_class, BaseModel):
        return model_class.model_json_schema()
    else:
        # 简单的dataclass或类型注解支持
        hints = get_type_hints(model_class)
        properties = {}
        required = []

        for field_name, field_type in hints.items():
            if field_name.startswith('_'):
                continue

            properties[field_name] = _type_to_schema(field_type)
            required.append(field_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required
        }


def _type_to_schema(field_type) -> Dict[str, Any]:
    """将Python类型转换为JSON Schema"""
    if field_type == str:
        return {"type": "string"}
    elif field_type == int:
        return {"type": "integer"}
    elif field_type == float:
        return {"type": "number"}
    elif field_type == bool:
        return {"type": "boolean"}
    else:
        return {"type": "string", "description": f"类型: {field_type}"}


def tool_function(name: str, description: str, examples: list[str] = None, **meta):
    """
    装饰器：自动注册函数到Function Call系统

    @tool_function(
        name="weather_query",
        description="查询天气",
        examples=["北京天气怎么样"]
    )
    def handle_weather(ctx: MessageContext, args: WeatherArgs) -> FunctionResult:
        pass
    """
    def wrapper(func):
        # 获取函数参数类型注解
        hints = get_type_hints(func)
        args_type = hints.get('args')

        if args_type:
            schema = build_schema_from_model(args_type)
        else:
            schema = {"type": "object", "properties": {}, "required": []}

        spec = FunctionSpec(
            name=name,
            description=description,
            parameters_schema=schema,
            handler=func,
            examples=examples or [],
            **meta
        )

        register_function(spec)
        return func

    return wrapper