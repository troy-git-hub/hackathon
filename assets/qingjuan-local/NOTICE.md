# 清卷本地排版资源

`paper.js`、`paper.css` 和 `figures.js` 是 2026-11-21 从此项目已有的清卷渲染适配层提取的本地快照，只包含卷面排版与配图，不包含网站登录、账户、部署、API配置或管理代码。

`expression.js` 同样来自项目已有的算术表达式解析器，供函数图离线求值，不使用 eval/Function；本地版本使用兼容 Qt WebEngine 的属性检查。`figures.js` 的函数曲线增加绘图区裁剪，避免越出坐标边框。

`katex/` 为项目现有本地 KaTeX 分发资源，许可保留于 `katex/LICENSE`。字体随包使用，不从外部站点加载。

本地预览由 `echo/widgets/qingjuan_preview.py` 生成，数据通过转义的JSON传入，拦截网络与非白名单文件请求。用户导出的HTML可独立离线使用。
