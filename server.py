import json
import requests
from datetime import datetime
from os import environ as env
from urllib.parse import quote_plus, urlencode

from helpers import d_format, ratings, format_rating

from authlib.integrations.flask_client import OAuth
from flask import Flask, redirect, render_template, session, url_for, request, flash

from cs50 import SQL


app = Flask(__name__)
app.secret_key = env.get("APP_SECRET_KEY")

oauth = OAuth(app)

oauth.register(
    "auth0",
    client_id=env.get("AUTH0_CLIENT_ID"),
    client_secret=env.get("AUTH0_CLIENT_SECRET"),
    client_kwargs={
        "scope": "openid profile email",
    },
    server_metadata_url=f'https://{env.get("AUTH0_DOMAIN")}/.well-known/openid-configuration',
)


# setting up the database
db = SQL(env.get("DATABASE_URL"))


# Controllers auth0 API
@app.route("/")
def home():

    if session:
        # collect user data
        user = {
            "name": session.get('user')['userinfo']['name'],
            "email": session.get('user')['userinfo']['email'],
            "picture": session.get('user')['userinfo']['picture']
        }

        userInDb = db.execute("SELECT * FROM userdb WHERE _email = ?", user['email'])


        registration = datetime.now()

        # if user not in db yet
        if len(userInDb) == 0:
            db.execute(
                "INSERT INTO userdb (_name, _email, first_login, picture) VALUES (?,?,?,?)", 
                user['name'], 
                user['email'],
                registration.strftime("%B %d, %Y %I:%M %p"),
                user['picture']
            )

    trend = requests.get("https://kitsu.io/api/edge/trending/anime")
    trending_api = trend.json()

    popular = requests.get("https://kitsu.io/api/edge/anime?sort=-averageRating&page[limit]=20&page[offset]=5")
    most_popular = popular.json()

    upcom = requests.get("https://kitsu.io/api/edge/anime?sort=-startDate&page[limit]=20")
    upcoming = upcom.json()

    new_discoveries_api = requests.get("https://kitsu.io/api/edge//anime?sort=-createdAt&page[limit]=20")
    new_discoveries = new_discoveries_api.json()

    recent_update_api = requests.get("https://kitsu.io/api/edge//anime?sort=-updatedAt&page[limit]=20")
    recent_update = recent_update_api.json()

    return render_template(
        "home.html",
        session=session.get("user"),
        trending=trending_api,
        popular=most_popular,
        upcoming=upcoming,
        new_discoveries=new_discoveries,
        recent_update=recent_update
    )


# SEARCH
@app.route("/search")
def search():
    query = request.args.get("q")

    # listen to the user input
    show = db.execute(
        "SELECT * FROM anime WHERE LOWER(en_title) LIKE ?",
        "%" + query.lower() + "%"
    )


    # return any data from the db that match the user input
    if len(show) > 0:
        return render_template("search.html", show=show)

    return "No data found"



# ANIME DETAILS
@app.route("/details/<int:id>")
def details(id):
    anime_details_api = requests.get(f"https://kitsu.io/api/edge/anime/{id}")
    anime_details = anime_details_api.json()

    found_in_kitsu = db.execute("SELECT kitsu_id FROM anime WHERE id = ?", id)


    if len(found_in_kitsu) == 0:
        insert_query = "insert into anime (kitsu_id, en_title, favorite_count, poster_image, first_release) values (?,?,?,?,?)"
        db.execute(
            insert_query,
            
        )

    data_attributes = anime_details['data']['attributes']

    details = {
        'launch date': d_format(data_attributes['createdAt']),
        'latest update': d_format(data_attributes['updatedAt']),
        'english title': data_attributes['canonicalTitle'],
        'age rating guide': data_attributes['ageRatingGuide'],
        'episode length': data_attributes['episodeLength'],
        'rating and review': ratings(data_attributes['ratingFrequencies'])
    }

    review_api = requests.get(anime_details['data']['relationships']['reviews']['links']['related'])
    anime_reviews = review_api.json()

    all_reviews = list()

    for i in range(4):

        try:
            review = anime_reviews['data'][i]

            reviews = review['attributes']['content']

            user_api = requests.get(review['relationships']['user']['links']['related'])
            user = user_api.json()

            all_reviews.append({
                "review": reviews,
                "user": user['data']['attributes']['name'],
                "profile": user['data']['attributes']['avatar']['original'],
                "publish_date": d_format(user['data']['attributes']['updatedAt']),
                "rating": format_rating(review['attributes']['rating'])
            })
        except:
            ...


    myreview_db = db.execute("SELECT * FROM review review WHERE anime_id = ?", id)
    reviews = list()
    for review in myreview_db:
        user = db.execute("SELECT _name, picture from userdb where id = ?", myreview_db[0]["sender_id"])

        reviews.append({
            "review": myreview_db[0]["content"],
            "sender": user[0]["_name"],
            "sender_picture": user[0]["picture"],
            "rate": myreview_db[0]["rate"],
            "posted_at": myreview_db[0]["posted_at"]
        })

    # return anime
    return render_template(
        "details.html", 
        session=session.get("user"),
        all_reviews=all_reviews,
        db_reviews=reviews,
        details=details,
        anime=anime_details
    )


# SEND REVIEW
@app.route("/send_review/<int:anime_id>", methods=["GET","POST"])
def send_review(anime_id):

    # if method not post
    if not request.method == "POST":
        flash("Please use correct method", "error")
        return render_template("message.html")

    review = request.form.get("review")
    sender_id = db.execute("SELECT id FROM userdb WHERE _email = ?", session.get("user")["userinfo"]["email"])

    # check in the db
    reviewDB = db.execute(
        "SELECT * FROM review WHERE sender_id = ? AND anime_id = ?", 
        sender_id[0]['id'], 
        anime_id
    )

    # check if user already left a review
    if len(reviewDB) > 0:
        flash("You already left a comment!")
        return render_template("message.html")


    db.execute(
        "INSERT INTO review (sender_id, anime_id, rate, content, posted_at) VALUES (?,?,?,?,?)", 
        sender_id[0]['id'], 
        anime_id, 
        request.form.get("rate"),
        review,
        datetime.now()
    )

    flash("Review sent! Please refresh the page to see updates.", "success")
    return render_template("message.html")



# /** TODO **/
# MY REVIEW
# PROFILE
@app.route("/profile")
def profile():
    if not session:
        return "Please Login first"

    return json.dumps(session.get("user"), indent=4)

# review
@app.route("/user_review")
def review():
    if not session:
        return "Please try login first"

    user_id = db.execute("SELECT id FROM userdb WHERE LOWER(_name) = ?", session.get("user")['userinfo']['name'].lower())
    reviews = db.execute("SELECT * FROM review WHERE sender_id = ?", user_id[0]["id"])

    return {
        "reviews": reviews,
        "user": user_id
    }

@app.route("/callback", methods=["GET", "POST"])
def callback():
    token = oauth.auth0.authorize_access_token()
    session["user"] = token
    return redirect("/")


@app.route("/login")
def login():
    return oauth.auth0.authorize_redirect(
        redirect_uri=url_for("callback", _external=True)
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(
        "https://"
        + env.get("AUTH0_DOMAIN")
        + "/v2/logout?"
        + urlencode(
            {
                "returnTo": url_for("home", _external=True),
                "client_id": env.get("AUTH0_CLIENT_ID"),
            },
            quote_via=quote_plus,
        )
    )


if __name__ == "__main__":
    app.run()