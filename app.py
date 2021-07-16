import os
import uuid
import random
import redis
import re
import math
from flask import Flask, session, redirect, url_for, request, render_template, make_response, abort
from dotenv import load_dotenv
from redisearch import Client, Query, aggregation, reducers
from datetime import datetime, timedelta, timezone

load_dotenv()
app = Flask(__name__)

# Set the secret key to some random bytes
app.secret_key = b'\xe8k\x0f\xc2\xd4\x1c\n\xaeU8g\x986&E\xe4'

REDIS_URL = os.getenv('REDIS_URL')

if REDIS_URL.startswith('rediss'):
    redisClient = redis.from_url(
        REDIS_URL, decode_responses=True, ssl_cert_reqs=None)
else:
    redisClient = redis.from_url(REDIS_URL, decode_responses=True)

redisearchClient = Client('articles', conn=redisClient)
aggregateClient = Client('analytics:search', conn=redisClient)


@app.template_filter('publishDateFormat')
def publishDateFormat(ts, format='%d %b %Y %H:%M'):
    return datetime.utcfromtimestamp(int(ts)).strftime(format)


@app.before_request
def before_request_func():
    """
    Run before each request

    Manages the session but reads in custom http request headers
    """
    if 'id' not in session:
        session['id'] = uuid.uuid4().hex
        app.logger.debug(f'new session with id {session["id"]}')


@app.route('/')
def home():
    """
    Renders the home page

    Display recently viewed articles (if any)
    Display popular articles (if any)
    """
    viewed = fetchRecentlyViewedArticles(session['id'])
    popular = fetchPopularArticles()
    recent = fetchMostRecentArticles()
    response = make_response(render_template(
        'home.html', viewed=viewed, popular=popular, recent=recent))
    return response


@app.route('/search')
def classicSearch():
    """
    Renders search results page for a "classic search"
    """
    q = request.args.get('q', '').strip()
    results = None
    searchId = None

    if len(q) <= 2:
        return make_response(render_template('search.html',
                                             results=results, search_id=searchId))

    """
    For classic search we are simply performing a phrase search

    This will return accurate results but will be very hit and miss
    with a small data set (and bad queries)

    To widen the net, additional synonyms should be added or one can widen
    the net by logical OR'ing each word eg.

    results, searchId = executeSearch(q.replace(' ','|'))

    https://oss.redislabs.com/redisearch/Query_Syntax.html
    """
    results, searchId = executeSearch(q)
    didYouMean = fetchDidYouMeanSuggestions(q)
    autoDidYouMean = False

    if didYouMean and not results.total:
        results, searchId = executeSearch(didYouMean['q'])
        autoDidYouMean = True

    return make_response(render_template('search.html',
                                         results=results, search_id=searchId,
                                         did_you_mean=didYouMean,
                                         auto_did_you_mean=autoDidYouMean))


@app.route('/instant-search')
def instantSearch():
    """
    Renders search results html fragment for an "instant search"

    This endpoint is invoked via Ajax
    """
    q = request.args.get('q', '').strip()
    # remove non-word characters because we are using prefix search
    q = re.sub(r'[^\w]+', ' ', q).strip()

    if not len(q) >= 2:
        abort(400)

    """
    build the search query

    for search as-you-type we are using prefix search functionality

    Also we are using logical ORs between words so that search
    is more "generous" with results but ensures docs with most/all
    keyword matches scores higher

    See https://oss.redislabs.com/redisearch/Query_Syntax.html#prefix_matching
    """
    q = '|'.join([word + '*' for word in q.split(' ')])
    results, searchId = executeSearch(q)

    response = make_response(render_template('search_result.html',
                                             results=results, search_id=searchId))
    return response


@app.route('/track-search-click/<search_id>/<position>/<article_id>')
def trackSearchClick(search_id, position, article_id):
    """
    Tracks an article click from search result and redirects to the view article page

    https://redis.io/commands/XADD
    """
    redisClient.xadd(
        'events:search:clicks',
        {
            '_version': 'v1',
            'search_id': search_id,
            'position': int(position),
            'article_id': article_id,
            'ip': request.remote_addr,
            'user_id': session.get('user_id', ''),
            'session_id': session['id'],
        }
    )

    return redirect(url_for('viewArticle', id=article_id))


@app.route('/article/<id>')
def viewArticle(id):
    """
    Renders a view article page

    Each article is indexed in the articles search index
    but implicitly each article is also stored as a Redis hash
    therefore its trivial to render a view article page from the hash data

    Alternatively, one can store atricles as JSON docs using the ReJson module
    https://oss.redislabs.com/redisjson/

    Overkill for this use case. Hashes are simple and fast
    """
    doc = redisClient.hgetall(id)

    if not doc:
        abort(404)

    # track article view event
    # https://redis.io/commands/XADD
    redisClient.xadd(
        'events:article:views',
        {
            '_version': 'v1',
            'type': 'view',
            'article_id': id,
            'article_title': doc['title'],
            'user_id': session.get('user_id', ''),
            'session_id': session['id'],
        }
    )

    viewed = fetchRecentlyViewedArticles(session['id'])
    return render_template('view.html', doc=doc, viewed=viewed)


@app.route('/analytics')
def analytics():
    """
    Renders the analytics dashboard page

    Uses current date + 24 hours as the default date range
    And uses an hourly bucket by default
    Date range and buckets configurable via query parameters

    Essentially we're mimicking the analytics features
    of elasticsearch app search

    https://static-www.elastic.co/v3/assets/bltefdd0b53724fa2ce/blt1bacf43a3868bc70/5dcc9ccf174f6e021220f330/screenshot-app-search_analytics.png

    See https://oss.redislabs.com/redisearch/Aggregations.html
    """
    start = request.args.get('start',
                             datetime.now(timezone.utc).strftime('%Y-%m-%d')).strip()
    end = request.args.get('end',
                           (datetime.strptime(start, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')).strip()
    # normalize bucket value to 1 hour windows
    bucket = ((int(request.args.get('bucket', 3600)) // 60) * 60) * 1000
    startTs = math.floor(datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()*1000)
    endTs = math.floor(datetime.strptime(end, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()*1000)

    if startTs >= endTs:
        abort(400)

    queries = []
    # total search queries for the period start -> end
    # https://oss.redislabs.com/redisearch/Aggregations.html#count
    queries.append(
        aggregation.AggregateRequest(
            f"@ts:[{startTs} {endTs}]"
        ).group_by([], reducers.count().alias('total_queries'))
    )

    # total search queries with no results for the period start -> end
    # https://oss.redislabs.com/redisearch/Aggregations.html#count
    queries.append(
        aggregation.AggregateRequest(
            f"@ts:[{startTs} {endTs}] @resultsTotal:[0 0]"
        ).group_by([], reducers.count().alias('total_queries_with_no_results'))
    )

    # total search clicks for the period start -> end
    # https://oss.redislabs.com/redisearch/Aggregations.html#sum
    queries.append(
        aggregation.AggregateRequest(
            f"@ts:[{startTs} {endTs}]"
        ).group_by([], reducers.sum('@clicks').alias('total_clicks'))
    )

    # total queries by time bucket for the period start -> end
    # https://oss.redislabs.com/redisearch/Aggregations.html#example_1_unique_users_by_hour_ordered_chronologically
    queries.append(
        aggregation.AggregateRequest(
            f"@ts:[{startTs} {endTs}]"
        ).apply(bucket=f"@ts - (@ts % {bucket})"
                ).apply(bucket="timefmt(@bucket/1000)"
                        ).group_by('@bucket', reducers.count().alias('total_queries_by_bucket')
                                   ).sort_by('@bucket')
    )

    # total clicks by time bucket for the period start -> end
    # https://oss.redislabs.com/redisearch/Aggregations.html#example_1_unique_users_by_hour_ordered_chronologically
    queries.append(
        aggregation.AggregateRequest(
            f"@ts:[{startTs} {endTs}]"
        ).apply(bucket=f"@ts - (@ts % {bucket})"
                ).apply(bucket="timefmt(@bucket/1000)"
                        ).group_by('@bucket', reducers.sum('@clicks').alias('total_clicks')
                                   ).sort_by('@bucket')
    )

    # total queries with no results by time bucket for the period start -> end
    # https://oss.redislabs.com/redisearch/Aggregations.html#example_1_unique_users_by_hour_ordered_chronologically
    queries.append(
        aggregation.AggregateRequest(
            f"@ts:[{startTs} {endTs}] @resultsTotal:[0 0]"
        ).apply(bucket=f"@ts - (@ts % {bucket})"
                ).apply(bucket="timefmt(@bucket/1000)"
                        ).group_by('@bucket', reducers.count().alias('total_queries_with_no_results_by_bucket')
                                   ).sort_by('@bucket')
    )

    # top queries for period start -> end
    # https://oss.redislabs.com/redisearch/Aggregations.html#example_2_sort_visits_to_a_specific_url_by_day_and_country
    queries.append(
        aggregation.AggregateRequest(
            f"@ts:[{startTs} {endTs}]"
        ).group_by(
            '@termNormalized', reducers.count().alias(
                'queries'), reducers.sum('@clicks').alias('total_clicks')
        ).sort_by(aggregation.Desc('@queries')).limit(0, 10)
    )

    # top queries with no results for period start -> end
    # https://oss.redislabs.com/redisearch/Aggregations.html#example_1_unique_users_by_hour_ordered_chronologically
    queries.append(
        aggregation.AggregateRequest(
            f"@ts:[{startTs} {endTs}] @resultsTotal:[0 0]"
        ).group_by(
            '@termNormalized', reducers.count().alias('queries')
        ).sort_by(aggregation.Desc('@queries')).limit(0, 10)
    )

    results = [aggregateClient.aggregate(q) for q in queries]

    analytics = {}
    analytics['total_queries'] = results[0].rows[0][1] if len(results[0].rows) else 0
    analytics['total_queries_with_no_results'] = results[1].rows[0][1] if len(results[1].rows) else 0
    analytics['total_clicks'] = results[2].rows[0][1] if len(results[2].rows) else 0

    """
    Warning some interesting code follows

    A bit gymnastics required here because redisearch aggregations does not (yet) have built-in windowing functionality

    Therefore relying on group by means we won't get buckets for windows where we have no data!

    For DIY windowing

    1. first we create empty buckets/windows upfront
    2. then for each line we want to plot we copy the empty buckets
    3. then update the empty bucket values with actual data available

    voila! time-based bucketing
    """
    buckets = dict([((datetime.utcfromtimestamp(i/1000).isoformat() + 'Z'), 0) for i in range(startTs, endTs, bucket)])

    analytics['graph'] = {}
    analytics['graph']['labels'] = list(buckets.keys())

    for k, r in {'queries': 3, 'clicks': 4, 'no_results': 5}.items():
        timeSeries = buckets.copy()
        timeSeries.update(
            dict([(row[1], int(row[3])) for row in results[r].rows])
        )
        analytics['graph'][k] = list(timeSeries.values())

    analytics['top_queries'] = [(r[1], r[3], r[5]) for r in results[6].rows]
    analytics['top_queries_with_no_results'] = [(r[1], r[3]) for r in results[7].rows]

    return render_template(
        'analytics.html',
        start=start,
        end=end,
        bucket=bucket,
        analytics=analytics)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Renders a mock login page

    Enter any email address. Password can be blank

    Goal is just to create minimal personalization
    """
    if request.method == 'POST':
        # pretend to authenticate
        session['email'] = request.form['email']
        session['user_id'] = random.randrange(10000)
        return redirect(url_for('home'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    """
    Basic logout functionality
    """
    # remove the username from the session if its there
    session.pop('email', None)
    return redirect(url_for('home'))


def fetchRecentlyViewedArticles(sessionId):
    """
    Fetch recently viewed articles for given sessionId
    """
    key = ":".join(['recently_viewed', sessionId])
    articleIds = redisClient.zrevrange(key, 0, -1)
    viewed = []

    # retrieve article titles for recently viewed set
    if len(articleIds):
        pipe = redisClient.pipeline(transaction=False)
        for articleId in articleIds:
            pipe.hget(articleId, 'title')
        articleTitles = pipe.execute()
        viewed = list(zip(articleIds, articleTitles))

    return viewed


def fetchPopularArticles():
    """
    Fetch list of popular articles (if any)
    """
    articleIds = redisClient.zrevrange('{popular_articles}', 0, 4)
    popular = []

    # retrieve article titles for popular articles set
    if len(articleIds):
        pipe = redisClient.pipeline(transaction=False)
        for articleId in articleIds:
            pipe.hget(articleId, 'title')
        articleTitles = pipe.execute()
        popular = list(zip(articleIds, articleTitles))

    return popular


def executeSearch(q):
    """
    Executes search query

    Employed by classic search and instant search functionality

    As the respective functionality is unique to the "q" parameter

    See https://oss.redislabs.com/redisearch/Query_Syntax.html
    """
    query = f"@title|blurb|body:{q} "
        # f"@country:{ {request.country} } " \
        # f"@platform:{ {request.platform} } " \
        #    f"@version:{ {request.version} }"
    # apply summarize and highlighting
    # See https://oss.redislabs.com/redisearch/Highlight.html
    redisearchQuery = Query(query).summarize(
        fields=['body'], num_frags=1, context_len=30).highlight(
        fields=['title', 'blurb', 'body'],
        tags=['<strong style="color: blue">', '</strong>'])
    app.logger.debug(query)
    results = redisearchClient.search(redisearchQuery)
    explain = redisearchClient.explain(redisearchQuery)
    app.logger.debug(explain)

    # publish the search query event to a stream
    # https://redis.io/commands/xadd
    searchId = redisClient.xadd(
        'events:search:queries',
        {
            '_version': 'v1',
            'query': query,
            'term_original': request.args.get('q', ''),
            'term_normalized': q,
            'results_total': results.total,
            'ip': request.remote_addr,
            'user_id': session.get('user_id', ''),
            'session_id': session['id'],
        }
    )

    return (results, searchId)


def fetchMostRecentArticles(offset=0, limit=5):
    """
    Fetch list of most recent articles by offset/limit
    """
    redisearchQuery = Query('*').sort_by('publishDate', asc=False).paging(offset, limit)
    return redisearchClient.search(redisearchQuery)


def fetchDidYouMeanSuggestions(q):
    """
    Fetches did you mean suggestions for given "q"

    See https://oss.redislabs.com/redisearch/Spellcheck.html
    """
    didYouMean = {}
    suggestions = redisearchClient.spellcheck(q)
    firstSuggestions = {k: v[0]['suggestion'] for k, v in suggestions.items()}
    if len(firstSuggestions):
        # todo simplify this code. it is terrible
        didYouMeanMap = dict([(k, False) for k in q.split(' ')])
        didYouMeanMap.update(firstSuggestions)
        didYouMean['q'] = " ".join(
            {(v if v else k): False for k, v in didYouMeanMap.items()}.keys())
        didYouMean['html'] = " ".join(
            {(("<strong><em>%s</em></strong>" % v) if v else k): 0 for k, v in didYouMeanMap.items()}.keys())

    return didYouMean
