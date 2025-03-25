from flask import Flask, Response, request
import requests
import time
import mistune
import xml.etree.ElementTree as ET
from xml.dom import minidom
from xml.sax.saxutils import escape
from api.config import plugin_info

# 常量定义
CACHE_TIMEOUT = 300  # 缓存超时时间（秒）
GITHUB_API_URL = "https://api.github.com/repos/unit-mesh/auto-dev/releases/latest"

# 缓存相关变量
_cache = {}

# XML模板定义
UPDATES_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<plugins>
    <plugin id="cc.unitmesh.devti" url="{download_url}" version="{version}">
        <idea-version since-build="{since_version}" until-build="{until_version}"/>
        <name>AutoDev</name>
        <vendor>UnitMesh</vendor>
        <description><![CDATA[<a href="https://github.com/unit-mesh/auto-dev">Github</a> | <a href="https://github.com/unit-mesh/auto-dev/issues">Issues</a>.
<br/>
<br/>
🧙‍AutoDev: The AI-powered coding wizard with multilingual support 🌐, auto code generation 🏗️, and a helpful bug-slaying
assistant 🐞! Customizable prompts 🎨 and a magic Auto Testing feature 🧪 included! 🚀]]></description>
        <change-notes>{change_notes}</change-notes>
    </plugin>
</plugins>
"""

app = Flask(__name__)

def fetch_release_info() -> dict:
    """从GitHub获取最新发布信息，使用缓存机制避免频繁请求"""
    cache_timestamp = _cache.get('release_info_timestamp', 0)
    if _cache and time.time() - cache_timestamp < CACHE_TIMEOUT:
        return _cache['release_info']

    response = requests.get(GITHUB_API_URL)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch GitHub release: {response.status_code}")
    
    data = response.json()
    _cache['release_info'] = data
    _cache['release_info_timestamp'] = time.time()
    return data

def is_version_in_range(version: str, since_version: str, until_version: str) -> bool:
    """检查版本是否在指定范围内
    
    :param version: 要检查的版本号
    :param since_version: 最低支持版本
    :param until_version: 最高支持版本（支持通配符，如'233.*'）
    :return: 是否在范围内
    """
    # 移除版本号中的前缀（如'IU-'）
    version = version.split('-')[-1]
    
    # 如果until_version包含通配符，只比较主版本号
    if until_version.endswith('.*'):
        until_version = until_version[:-2]
        version = version[:len(until_version)]
        since_version = since_version[:len(until_version)]
    
    return since_version <= version <= until_version

def fetch_latest_release(idea_version: str, build_version: str = None) -> dict:
    """获取指定IDE版本的最新插件发布信息
    
    :param idea_version: IDEA版本号（如'241'）
    :param build_version: IDEA构建版本号（如'IU-243.26053.27'）
    """
    # 如果指定了idea_version，直接使用idea_version
    matched_version = idea_version
    # 如果没有提供idea_version, 则使用build_version进行匹配
    if not matched_version:
        for version, info in plugin_info["versions"].items():
            if is_version_in_range(build_version, info["since_version"], info["until_version"]):
                matched_version = version
                break
        
    if not matched_version:
        raise ValueError(f"Unsupported IDE version: {build_version}")

    data = fetch_release_info()
    version_info = plugin_info["versions"][matched_version]
    tag_name = data["tag_name"]
    version = tag_name.lstrip("v")
    
    # 查找对应版本的插件文件
    plugin_file = next(
        (asset["browser_download_url"] for asset in data["assets"] 
         if f"autodev-jetbrains-{version}-{matched_version}.zip" in asset["name"]),
        None
    )

    if not plugin_file:
        raise Exception(f"Plugin file not found for version {version} {matched_version}")

    change_notes = mistune.html(data.get("body", ""))

    return {
        "version": version,
        "since_version": version_info["since_version"],
        "until_version": version_info["until_version"],
        "download_url": plugin_file,
        "change_notes": escape(change_notes)
    }

def generate_updates_xml(release_info: dict) -> str:
    """生成格式化的更新XML文件"""
    xml_content = UPDATES_XML_TEMPLATE.format(**release_info)
    dom = minidom.parseString(xml_content)
    return dom.toprettyxml(indent="    ")

@app.route('/')
def home():
    """首页路由，显示支持的IDE版本列表"""
    versions = plugin_info["versions"].keys()
    version_links = "\n".join(f"    <li><a href='/{version}/updatePlugins.xml'>{version}</a></li>" for version in versions)
    return f"""
    <a href="https://github.com/unit-mesh/auto-dev">Auto-Dev Plugin Repository Server</a>
    <ul>
{version_links}
    </ul>
    """

@app.route('/about')
def about():
    """关于页面路由"""
    return '<a href="https://github.com/unit-mesh/auto-dev">Auto-Dev Plugin Repository Server</a>'

@app.route('/<idea_version>/updatePlugins.xml')
@app.route('/updatePlugins.xml')
def update_plugins(idea_version=''):
    """
    生成插件更新XML文件的路由
    
    :param idea_version: 路径指定的IDEA版本
    """
    build_version = request.args.get('build', None)
    try:
        release_info = fetch_latest_release(idea_version, build_version)
        xml_content = generate_updates_xml(release_info)
        return Response(xml_content, mimetype='application/xml')
    except ValueError as e:
        return str(e), 400
    except Exception as e:
        return str(e), 500