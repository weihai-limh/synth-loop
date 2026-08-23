"""资源消费分析器：分析资源消费方式，将资源嵌入工具或注入上下文"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AssetConsumer:
    """资源消费分析器"""
    
    def consume(
        self,
        tools: list[dict[str, Any]],
        assets: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        分析资源消费方式
        
        Args:
            tools: strata-match 返回的工具列表
            assets: strata-match 返回的资源列表
        
        Returns:
            (processed_tools, independent_assets)
            - processed_tools: 处理后的工具列表（已嵌入资源）
            - independent_assets: 独立资源列表（注入上下文）
        """
        if not assets:
            return tools, []
        
        if not tools:
            # 无工具，所有资源独立注入
            return tools, assets
        
        # 分析工具参数，尝试匹配资源
        processed_tools = []
        matched_asset_ids = set()
        
        for tool in tools:
            tool_name = tool.get("name", "")
            params = tool.get("params", [])
            command = tool.get("command", "")
            
            # 尝试匹配资源
            matched_assets = self._match_assets_to_tool(
                tool_name=tool_name,
                params=params,
                command=command,
                assets=assets
            )
            
            if matched_assets:
                # 有匹配的资源，生成多个工具实例
                for asset in matched_assets:
                    processed_tool = self._embed_asset_to_tool(tool, asset)
                    processed_tools.append(processed_tool)
                    matched_asset_ids.add(asset.get("id"))
            else:
                # 无匹配资源，保持原样
                processed_tools.append(tool)
        
        # 收集独立资源（未被工具消费的）
        independent_assets = [
            asset for asset in assets
            if asset.get("id") not in matched_asset_ids
        ]
        
        logger.info(
            f"Resource consumption analysis complete: "
            f"tools: {len(tools)}, "
            f"assets: {len(assets)}, "
            f"matched: {len(matched_asset_ids)}, "
            f"independent: {len(independent_assets)}"
        )
        
        return processed_tools, independent_assets
    
    def _match_assets_to_tool(
        self,
        tool_name: str,
        params: list[str],
        command: str,
        assets: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        匹配资源到工具参数
        
        基于资源描述（described_cn）和工具参数进行匹配
        """
        matched = []
        
        for asset in assets:
            asset_subtype = asset.get("subtype", "")
            asset_desc = asset.get("described_cn", "") or asset.get("described", "")
            
            # 检查资源类型是否与工具参数匹配
            for param in params:
                param_lower = param.lower()
                
                # 匹配规则：
                # 1. 参数名包含资源类型关键词
                # 2. 资源描述包含参数名关键词
                if self._is_match(param_lower, asset_subtype, asset_desc):
                    matched.append(asset)
                    logger.debug(f"asset {asset.get('name')} matched tool {tool_name} param {param}")
                    break
        
        return matched
    
    def _is_match(
        self,
        param_name: str,
        asset_subtype: str,
        asset_description: str
    ) -> bool:
        """判断资源是否匹配工具参数"""
        # 关键词映射
        image_keywords = ["image", "img", "picture", "photo", "图片", "图像", "参考图"]
        pose_keywords = ["pose", "skeleton", "骨架", "姿势"]
        depth_keywords = ["depth", "深度"]
        style_keywords = ["style", "风格", "样式"]
        
        param_lower = param_name.lower()
        asset_desc_lower = asset_description.lower()
        
        # 检查参数名是否包含图片相关关键词
        if any(kw in param_lower for kw in image_keywords):
            # 检查资源是否是图片类型
            if asset_subtype.startswith("image_"):
                return True
        
        # 检查参数名是否包含特定类型关键词
        if any(kw in param_lower for kw in pose_keywords):
            if asset_subtype == "image_pose":
                return True
        
        if any(kw in param_lower for kw in depth_keywords):
            if asset_subtype == "image_depth":
                return True
        
        if any(kw in param_lower for kw in style_keywords):
            if asset_subtype == "image_style":
                return True
        
        return False
    
    def _embed_asset_to_tool(
        self,
        tool: dict[str, Any],
        asset: dict[str, Any]
    ) -> dict[str, Any]:
        """
        将资源嵌入工具
        
        生成一个新的工具实例，资源 URL 已预填
        """
        import copy
        
        # 深拷贝工具
        processed_tool = copy.deepcopy(tool)
        
        # 获取资源信息
        asset_url = asset.get("url", "")
        asset_name = asset.get("name", "")
        asset_subtype = asset.get("subtype", "")
        
        # 替换命令模板中的资源参数
        command = processed_tool.get("command", "")
        if command and asset_url:
            # 查找并替换资源相关参数
            params = processed_tool.get("params", [])
            for param in params:
                param_lower = param.lower()
                if any(kw in param_lower for kw in ["image", "img", "picture", "photo", "图片", "图像", "参考图", "pose", "style", "depth"]):
                    command = command.replace(f"{{{param}}}", asset_url)
                    # 从参数列表中移除已嵌入的参数
                    processed_tool["params"] = [p for p in params if p != param]
                    break
            
            processed_tool["command"] = command
        
        # 添加资源元信息
        processed_tool["_embedded_asset"] = {
            "name": asset_name,
            "subtype": asset_subtype,
            "url": asset_url
        }
        
        # 更新工具名称以区分不同资源
        original_name = processed_tool.get("name", "")
        processed_tool["name"] = f"{original_name}_{asset_name}"
        processed_tool["description"] = (
            f"{processed_tool.get('description', '')} "
            f"(使用{asset.get('described_cn', asset_name)})"
        )
        
        return processed_tool
    
    def format_assets_for_context(
        self,
        assets: list[dict[str, Any]]
    ) -> str:
        """
        将资源格式化为上下文文本
        
        用于注入到临时上下文
        """
        if not assets:
            return ""
        
        lines = ["可用资源："]
        
        for i, asset in enumerate(assets, 1):
            name = asset.get("name_cn") or asset.get("name", "")
            desc = asset.get("described_cn") or asset.get("described", "")
            url = asset.get("url", "")
            subtype = asset.get("subtype", "")
            
            line = f"{i}. {name}"
            if desc:
                line += f" - {desc}"
            line += f" ({subtype})"
            if url:
                line += f"\n   URL: {url}"
            
            lines.append(line)
        
        return "\n".join(lines)


# 全局实例
_consumer: Optional[AssetConsumer] = None


def get_asset_consumer() -> AssetConsumer:
    """获取资源消费分析器实例"""
    global _consumer
    if _consumer is None:
        _consumer = AssetConsumer()
    return _consumer
