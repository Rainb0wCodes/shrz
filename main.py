import os
import re
import json
import time
import xxhash
import sqlite3
import requests

from pygments import highlight
from pygments.lexers import guess_lexer_for_filename
from pygments.lexers.special import TextLexer
from pygments.formatters import ImageFormatter
from pygments.styles import get_style_by_name

from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from flask import render_template, Flask, request, make_response, g, send_from_directory, redirect

from style import DraculaStyle
from htmlmin.main import minify

PREFIX = "https://[REDACTED]/shrz"
FONT_SIZE = 40
# SEED = time.time_ns()

# update every time db schema is changed
SEED = 4

app = Flask(__name__)
app.secret_key = os.getenv(
    'SECRET_KEY', 'this is my secret key (insecure)')
app.config["APPLICATION_ROOT"] = "/shrz"

code_font = ImageFont.truetype("font.ttf", FONT_SIZE)


def render_code_to_image(code: str, line_numbers, lexer):
    return highlight("\n".join(code.split("\n")[line_numbers[0] - 1:line_numbers[1]]), lexer, ImageFormatter(line_number_start=line_numbers[0], font_name="Cascadia Code", style=DraculaStyle, line_number_fg="#ADBAC7", line_number_bg="#303136", line_number_separator=False))


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g.db = sqlite3.connect("shrz.db")
    return db


@app.route('/xx/<object_hash>', methods=['GET'])
def xx(object_hash: str):
    cur = get_db().cursor()
    if object_hash.endswith(".json"):
        object_data = cur.execute(
            "SELECT oembed_data FROM objects WHERE hash = ?", (object_hash[:-5],)).fetchone()
        cur.close()

        if object_data is None:
            return make_response("{}", 404)

        return object_data[0]

    object_data = cur.execute(
        "SELECT meta_tags, title, redirect_url FROM objects WHERE hash = ?", (object_hash,)).fetchone()
    cur.close()
    if object_data is None:
        return make_response(render_template("error.html", message="Error: invalid object hash"), 404)

    if "text/html" in request.headers.get('Accept', ''):
        return redirect(object_data[2], 307)
    return render_template("oembed.html", tags=object_data[0], title=object_data[1], current_url=PREFIX + "/xx/" + object_hash)


@app.route('/ass/<object_hash>', methods=['GET'])
def ass(object_hash: str):
    cur = get_db().cursor()
    image = cur.execute(
        "SELECT image FROM objects WHERE hash = ?", (object_hash[:-4],)).fetchone()
    cur.close()

    if image is None:
        return make_response(render_template("error.html", message="Error: invalid object hash"), 404)

    if image[0] is None:
        return make_response(render_template("error.html", message="Error: object does not have image"), 404)

    res = make_response(image[0])
    res.headers['Content-Type'] = 'image/png'
    return res


@app.route('/font.ttf')
def static_file():
    return send_from_directory(".", "font.ttf", mimetype="font/ttf", as_attachment=False)


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == "GET":
        return render_template('index.html')

    if "url" not in request.form:
        return make_response(render_template('index.html', message='Error: invalid form data'), 400)

    url = request.form.get("url")
    # if not request.form.get("url")
    # "".startswith("")
    if re.match(r"https:\/\/github\.com\/[a-zA-Z0-9-]+\/[a-zA-Z0-9-]+\/blob\/[^\/]+\/.+", url) == None:
        return make_response(render_template('index.html', message='Error: unsupported url'), 400)

    url_hash = url.split("#")[1] if "#" in url else ""

    if len(url_hash) < 1 or not url_hash.startswith("L"):
        # return make_response(render_template('index.html', message='Error: url does not contain line numbers'), 400)
        print("URL does not contain line numbers, using first few")
        line_numbers = [1, 10]
    else:
        # L05-L09
        split = url_hash.split("L")
        if len(split) > 2:
            line_numbers = [int(split[1][:-1]), int(split[2])]
        else:
            line_numbers = [int(split[1]), int(split[1]) + 10]

    repo = url.split("/blob/")[0].split("https://github.com/")[1]
    path = url.split("/blob/")[1]
    file_contents = requests.get(
        "https://raw.githubusercontent.com/{}/{}".format(repo, path)).text
    line_numbers[1] = min(line_numbers[1], len(file_contents.split("\n")))
    print("https://raw.githubusercontent.com/{}/{}".format(repo, path),
          file_contents, len(file_contents.split("\n")), line_numbers)

    try:
        lexer = guess_lexer_for_filename(
            path.split("/")[-1].split("#")[0], file_contents)
    except Exception as e:
        lexer = TextLexer()
        print(e)

    hsh = xxhash.xxh32(url, seed=SEED).hexdigest()
    cur = get_db().cursor()
    cur.execute("INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?,?,?)", (hsh, "Title", '<meta name="theme-color" content="#1E90FF"><meta property="og:title" content="{}"><meta property="og:image" content="{}"><meta name="twitter:card" content="summary_large_image"><link type="application/json+oembed" href="{}">'.format(
        path.split("/")[-1], PREFIX + "/ass/" + hsh + ".png", PREFIX + "/xx/" + hsh + ".json"), '{{"type":"photo","author_name":"shrz"}}'.format(json.dumps(PREFIX + "/ass/" + hsh + ".png")), render_code_to_image(file_contents, line_numbers, lexer), url, -1))
    cur.close()
    g.db.commit()

    return render_template('index.html', message='Success!', embed_url=PREFIX + "/xx/" + hsh)


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
@app.errorhandler(404)

def not_found(e):
    print(e)
    return request.url

@app.after_request
def response_minify(response):
    """
    minify html response to decrease site traffic
    """
    if response.content_type == u'text/html; charset=utf-8':
        response.set_data(
            minify(response.get_data(as_text=True))
        )

        return response
    return response

with app.app_context():
    cur = get_db().cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS objects (hash TEXT PRIMARY KEY, title TEXT NOT NULL, meta_tags TEXT NOT NULL, oembed_data TEXT NOT NULL, image BLOB, redirect_url TEXT, uploader_id INTEGER NOT NULL)")

# app.run("0.0.0.0", 3050)
