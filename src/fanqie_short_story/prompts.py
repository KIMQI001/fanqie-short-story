"""All prompt templates as module-level constants. Keep prompts here, not in
generator modules, so they're easy to A/B without touching logic."""


OUTLINE_SYSTEM = (
    "你是一个网文短篇大纲编辑。严格按用户指定的 markdown 结构输出："
    "## 幕 (5-8 条) / ## 人物 / ## 设定 / ## 核心冲突。"
    "不要写正文，不要写开场白，不要 markdown 围栏。"
)

OUTLINE_USER_TEMPLATE = """钩子: {hook}
类型: {genre}
目标字数: {target_length}
风格: {tone}

输出一份 5-8 幕的短篇大纲，每幕一句话（30 字内）。
人物列表：主角、反派、关键配角各 1-3 人。
设定：100 字以内。
核心冲突：1 句话。

按以下 markdown 结构输出：

## 幕
1. <第一幕>
2. <第二幕>
...

## 人物
- <名字>：<角色>，<弧光>

## 设定
<100 字以内>

## 核心冲突
<1 句话>
"""


BODY_SYSTEM = (
    "你是一个网文短篇作者。直接写正文，"
    "开场 200 字内必须出现：冲突 + 主角目标 + 钩子句。"
    "结尾 500 字内必须收束核心冲突，不要'未完待续'。"
    "不要写大纲、不要写'以下是正文'等元描述，不要 markdown 围栏。"
)

BODY_USER_TEMPLATE = """钩子: {hook}
类型: {genre}
目标字数: {target_length}
风格: {tone}

## 大纲
{outline}

{critique_block}

按大纲写正文，目标 {target_length} 字。"""


TITLE_SYSTEM = "你是网文短篇标题编辑。"

TITLE_USER_TEMPLATE = """钩子: {hook}
类型: {genre}

## 正文开头
{body_head}

请生成 {n} 个候选标题，每行一个。标题 ≤ 30 字，钩子感强（冲突 / 反转 / 数字）。"""


SYNOPSIS_SYSTEM = "你是网文短篇简介编辑。"

SYNOPSIS_USER_TEMPLATE = """钩子: {hook}
类型: {genre}

## 正文开头
{body_head}

写一段简介，{n} 字左右，前 30 字必须抓人。"""
