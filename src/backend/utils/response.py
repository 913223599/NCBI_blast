from typing import Any, Dict, Optional

class BioResponse:
    @staticmethod
    def ok(data: Any = None, **metadata) -> Dict[str, Any]:
        """
        构建成功的 API 响应
        :param data: 业务数据内容
        :param metadata: 可选的附加元数据
        """
        response = {"success": True}
        if data is not None:
            if isinstance(data, dict):
                response.update(data)
            else:
                response["data"] = data
        if metadata:
            response.update(metadata)
        return response

    @staticmethod
    def fail(message: str, status_code: int = 500) -> Dict[str, Any]:
        """
        构建失败的 API 响应
        :param message: 错误描述信息
        :param status_code: 内部错误码 (非 HTTP 状态码)
        """
        return {
            "success": False,
            "error": message,
            "status_code": status_code
        }
