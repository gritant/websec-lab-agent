"""页面侦察：提取标题、表单、链接、URL 参数与 HTML 注释。

这是 Agent 的「眼睛」—— 模型不渲染页面，只消费这里的结构化摘要。
"""

from bs4 import BeautifulSoup, Comment


def summarize_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    forms = []
    for f in soup.find_all("form"):
        inputs = []
        for i in f.find_all(["input", "textarea", "select"]):
            inputs.append({
                "name": i.get("name"),
                "type": i.get("type", i.name),
                "value": (i.get("value") or "")[:80],
            })
        forms.append({
            "action": f.get("action"),
            "method": (f.get("method") or "GET").upper(),
            "inputs": inputs,
        })

    links = []
    params = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        links.append(href)
        if "?" in href:
            query = href.split("?", 1)[1]
            for pair in query.split("&"):
                params.add(pair.split("=", 1)[0])
    links = links[:30]

    comments = [c.strip()[:200] for c in soup.find_all(string=lambda t: isinstance(t, Comment))][:10]

    return {
        "title": title,
        "forms": forms,
        "links": links,
        "query_params": sorted(params),
        "html_comments": comments,
    }
