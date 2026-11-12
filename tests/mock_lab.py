"""本地 Mock 靶场：模拟一个「SQL 注入登录绕过」练习题。

模拟的漏洞后端等价于以下拼接 SQL（教学演示，不运行真实 SQL）：
    SELECT username FROM users WHERE username='{username}' AND password='{password}'

攻击方式与 PortSwigger 真实靶场一致：
    username = administrator'--   （引号闭合 + 注释掉密码条件）
登录成功后，首页出现「Congratulations, you solved the lab!」横幅，
check_solved 工具即据此判定通关。

仅监听 127.0.0.1，仅供本项目测试使用。
"""

from flask import Flask, redirect, request

app = Flask(__name__)

PASSWORDS = {
    "administrator": "h4ck3rAc4d3my",
    "wiener": "peter123",
}
STATE = {"solved": False}


def vulnerable_login(username: str, password: str):
    """手工模拟拼接 SQL 的执行结果。"""
    # 正常账号密码
    if username in PASSWORDS and PASSWORDS[username] == password:
        return username
    # 模拟注入：administrator'-- 把密码条件注释掉，仅剩 username='administrator'
    if username.startswith("administrator'") and "--" in username:
        return "administrator"
    return None


@app.route("/")
def home():
    banner = (
        '<div class="notification">Congratulations, you solved the lab!</div>'
        if STATE["solved"] else ""
    )
    return f"""<html><head><title>Mock Lab: SQL injection login bypass</title></head>
<body>{banner}
<h1>Mock Lab — SQL injection login bypass</h1>
<p>Welcome to the mock lab. Please <a href="/login">log in</a>.</p>
</body></html>"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return """<html><head><title>Login</title></head><body>
<h1>Log in</h1>
<form method="post" action="/login">
  <input type="text" name="username" placeholder="Username">
  <input type="password" name="password" placeholder="Password">
  <button type="submit">Log in</button>
</form>
</body></html>"""
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    user = vulnerable_login(username, password)
    if user == "administrator":
        STATE["solved"] = True
        return redirect("/")
    return "<html><body><p>Invalid username or password.</p></body></html>"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)
