from flask import Flask, render_template, request, jsonify, session, send_from_directory
import os
from dotenv import load_dotenv
import requests
from newspaper import Article
import json
import re
from datetime import datetime, timedelta
from functools import wraps
import time
from gnews import GNews
import threading
from bs4 import BeautifulSoup

class HistoryManager:
    def __init__(self, session, key, max_items=10):
        self.session = session
        self.key = key
        self.max_items = max_items
    
    def add_item(self, item):
        if self.key not in self.session:
            self.session[self.key] = []
        self.session[self.key] = [item] + self.session[self.key][:self.max_items-1]
        self.session.modified = True
    
    def get_items(self):
        return self.session.get(self.key, [])
    
    def delete_item(self, index):
        if self.key in self.session:
            self.session[self.key].pop(index)
            self.session.modified = True
            return True
        return False

# Simple rate limiting
class RateLimiter:
    def __init__(self, max_requests, time_window):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = {}
    
    def is_allowed(self, key):
        now = time.time()
        self.cleanup(now)
        
        if key not in self.requests:
            self.requests[key] = []
        
        self.requests[key].append(now)
        
        return len(self.requests[key]) <= self.max_requests
    
    def cleanup(self, now):
        for key in list(self.requests.keys()):
            self.requests[key] = [t for t in self.requests[key] if now - t < self.time_window]
            if not self.requests[key]:
                del self.requests[key]

# Create rate limiters
api_limiter = RateLimiter(max_requests=10, time_window=60)  # 10 requests per minute
scrape_limiter = RateLimiter(max_requests=5, time_window=60)  # 5 requests per minute

def rate_limit(limiter):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not limiter.is_allowed(request.remote_addr):
                return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
            return f(*args, **kwargs)
        return wrapped
    return decorator

load_dotenv()

app = Flask(__name__)
# Use environment variable for session key, fallback to random for development
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

if not DEEPSEEK_API_KEY:
    raise ValueError("DEEPSEEK_API_KEY environment variable is not set")

class APIError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code

def error_response(message, status_code=400):
    return jsonify({
        'success': False,
        'error': message
    }), status_code

def success_response(data):
    return jsonify({
        'success': True,
        **data
    })

def clean_article_text(text):
    # Remove common promotional phrases and irrelevant content
    promotional_patterns = [
        r"Follow us on \w+",
        r"Like us on \w+",
        r"Subscribe to our \w+",
        r"Click here to \w+",
        r"Don't forget to \w+",
        r"Check out our \w+",
        r"Read more: https?://\S+",
        r"Source: https?://\S+",
        r"Credit: \S+",
        r"Image: \S+",
        r"Photo: \S+",
        r"Advertisement",
        r"Sponsored",
        r"Related Articles:",
        r"You might also like:",
        r"Share this article",
        r"Tags:",
        r"\[.*?\]",  # Remove content in square brackets
        r"https?://\S+",  # Remove URLs
    ]
    
    # Apply each pattern
    for pattern in promotional_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # Remove multiple newlines and spaces
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    
    # Remove lines that are too short (likely navigation elements or single words)
    lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 30]
    
    # Join the lines back together
    text = '\n\n'.join(lines)
    
    return text.strip()

def get_kpop_prompt(original_text):
    return f"""You are a professional K-pop news article writer with extensive experience in writing for major K-pop news websites. 
    Rewrite the following article in an engaging and professional K-pop news style while maintaining accuracy and adding relevant context where appropriate. 
    Use a tone that appeals to K-pop fans while maintaining journalistic integrity.
    Keep the writing style similar to popular K-pop news sites like Soompi, allkpop, or Koreaboo.
    
    IMPORTANT RULES:
    1. DO NOT add any quotes or statements that are not present in the original article
    2. DO NOT make up or generate any statements from people
    3. ONLY include quotes that are directly from the original article
    4. If there are no statements or quotes in the original, do not add any
    5. Stick strictly to the facts presented in the original article
    
    Format your response in Markdown with:
    - A catchy headline as an H1 (#)
    - Proper paragraphs with line breaks
    - Important quotes in blockquotes (>) ONLY if they exist in the original
    - Emphasis on key points using bold or italic
    - Lists where appropriate
    - Artist/group names in bold
    
    Original article to rewrite:
    {original_text}
    
    Important guidelines:
    - Maintain factual accuracy
    - Use K-pop industry standard terminology
    - Include idol/group names consistently (in bold)
    - Keep the tone engaging but professional
    - Add relevant context when necessary
    - Format with appropriate paragraphs and markdown
    - Use present tense for news reporting
    - NO fabricated quotes or statements
    """

def rewrite_article(text, url='', title=''):
    try:
        if not text:
            raise APIError("No text provided for rewriting")
            
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a professional K-pop news article writer. Format your responses in Markdown. NEVER add statements or quotes that are not in the original article."},
                {"role": "user", "content": get_kpop_prompt(text)}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
        response.raise_for_status()
        
        result = response.json()['choices'][0]['message']['content']
        
        history_manager = HistoryManager(session, 'article_history')
        history_item = {
            'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'original': text,
            'rewritten': result,
            'url': url,
            'title': title
        }
        history_manager.add_item(history_item)
        
        return result
    except requests.exceptions.RequestException as e:
        raise APIError(f"API request failed: {str(e)}", 503)
    except Exception as e:
        raise APIError(str(e))

def scrape_article(url):
    try:
        if not url or not url.startswith(('http://', 'https://')):
            return {'error': 'Invalid URL. Please provide a valid HTTP or HTTPS URL.'}
            
        article = Article(url)
        article.download()
        article.parse()
        
        # Get the title and main text content
        title = article.title
        text = article.text
        
        if not title or not text:
            return {'error': 'Could not extract content from the provided URL.'}
        
        # Clean the article content
        cleaned_text = clean_article_text(text)
        
        if not cleaned_text:
            return {'error': 'No usable content found after cleaning the article.'}
        
        # Add title at the beginning
        full_article = f"{title}\n\n{cleaned_text}"
        
        return {
            'text': full_article,
            'url': url,
            'title': title
        }
    except Exception as e:
        error_message = str(e)
        if 'Failed to download' in error_message:
            return {'error': 'Could not access the URL. Please check if the URL is correct and accessible.'}
        elif 'Timeout' in error_message:
            return {'error': 'Request timed out. Please try again.'}
        else:
            return {'error': f'An error occurred while processing the article: {error_message}'}

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/rewrite', methods=['POST'])
@rate_limit(api_limiter)
def rewrite():
    try:
        data = request.json
        text = data.get('text', '')
        url = data.get('url', '')
        title = data.get('title', '')
        rewritten = rewrite_article(text, url, title)
        return success_response({'result': rewritten})
    except APIError as e:
        return error_response(str(e), e.status_code)
    except Exception as e:
        return error_response(str(e))

@app.route('/scrape', methods=['POST'])
@rate_limit(scrape_limiter)
def scrape():
    data = request.json
    url = data.get('url', '')
    result = scrape_article(url)
    if isinstance(result, dict):
        return jsonify(result)
    else:
        return jsonify({'error': result})

@app.route('/history', methods=['GET'])
def get_history():
    history_manager = HistoryManager(session, 'article_history')
    return jsonify({'history': history_manager.get_items()})

@app.route('/history/delete/<int:index>', methods=['DELETE'])
def delete_history_item(index):
    history_manager = HistoryManager(session, 'article_history')
    if history_manager.delete_item(index):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Item not found'}), 400

@app.route('/instagram')
def instagram():
    return render_template('instagram.html')

@app.route('/instagram_history', methods=['GET'])
def get_instagram_history():
    history_manager = HistoryManager(session, 'instagram_history')
    return jsonify({'history': history_manager.get_items()})

@app.route('/instagram_history/delete/<int:index>', methods=['DELETE'])
def delete_instagram_history_item(index):
    history_manager = HistoryManager(session, 'instagram_history')
    if history_manager.delete_item(index):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Item not found'}), 400

def parse_instagram_content(content):
    """Parse and validate Instagram content from AI response"""
    try:
        # Remove code block markers if present
        content = re.sub(r'^```\w*\n|```$', '', content, flags=re.MULTILINE).strip()
        
        # Parse JSON content
        data = json.loads(content)
        
        # Validate and clean headlines
        headlines = data.get('headlines', [])
        if isinstance(headlines, str):
            headlines = [headlines]
        headlines = [str(h).strip() for h in headlines]
        headlines = [re.sub(r'\s+', ' ', h) for h in headlines]
        headlines = [h[:77] + "..." if len(h) > 80 else h for h in headlines]
        headlines = [h for h in headlines if h.strip()][:3]
        
        # Validate and clean captions
        captions = data.get('captions', [])
        if isinstance(captions, str):
            captions = [captions]
        captions = [str(c).strip() for c in captions][:3]
        
        # Ensure we have 3 items for both
        while len(headlines) < 3:
            headlines.append(f"K-pop News Update {len(headlines) + 1}")
        
        while len(captions) < 3:
            captions.append(f"Stay updated with the latest K-pop news! #Kpop (Variation {len(captions) + 1})")
        
        return {
            'headlines': headlines,
            'captions': captions
        }
    except json.JSONDecodeError:
        raise APIError("Failed to parse AI response")
    except Exception as e:
        raise APIError(f"Error processing Instagram content: {str(e)}")

@app.route('/generate_instagram', methods=['POST'])
@rate_limit(api_limiter)
def generate_instagram():
    try:
        data = request.json
        url = data.get('url', '')
        
        # Scrape the article
        article_data = scrape_article(url)
        if 'error' in article_data:
            raise APIError(article_data['error'])
        
        # Generate Instagram content using Deepseek
        prompt = f"""As an expert K-pop social media manager, create Instagram content for this article.
        
        Article Title: {article_data['title']}
        Article Content: {article_data['text']}
        
        Create THREE headlines (max 80 chars) and THREE detailed captions following these guidelines:

        Headline Guidelines:
        - Keep headlines concise but impactful
        - Focus on the key news or announcement
        - Use engaging language that appeals to K-pop fans
        - Maximum 80 characters per headline

        Caption Guidelines:
        - Write detailed, professional captions (200-300 words each)
        - NO emojis - maintain professional tone
        - First caption: Focus on news details and facts
        - Second caption: Emphasize artist/group achievements and milestones
        - Third caption: Create engagement through discussion points
        - Include relevant hashtags at the end (max 5-6 hashtags)
        - Use proper formatting with line breaks for readability
        - Maintain journalistic integrity while appealing to fans
        - Add context when necessary for international fans

        Provide the content in this JSON format:
{{
    "headlines": [
        "First headline here",
        "Second headline here",
        "Third headline here"
    ],
    "captions": [
        "First caption focusing on detailed news coverage",
        "Second caption highlighting achievements and impact",
        "Third caption encouraging fan engagement and discussion"
    ]
}}"""
        
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            DEEPSEEK_API_URL,
            headers=headers,
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You are a K-pop social media manager. Respond only with the requested JSON format."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.65,
                "max_tokens": 1000
            }
        )
        
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        
        # Parse and validate the content
        instagram_content = parse_instagram_content(content)
        
        # Save to history
        history_manager = HistoryManager(session, 'instagram_history')
        history_item = {
            'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'headlines': instagram_content['headlines'],
            'captions': instagram_content['captions'],
            'url': url
        }
        history_manager.add_item(history_item)
        
        return success_response(instagram_content)
        
    except requests.exceptions.RequestException as e:
        return error_response(f"API request failed: {str(e)}", 503)
    except APIError as e:
        return error_response(str(e), e.status_code)
    except Exception as e:
        return error_response(str(e))

# Cache for trending news
trending_news_cache = {
    'data': [],
    'last_updated': None
}

def fetch_trending_kpop_news():
    """Fetch trending K-pop news from multiple sources"""
    try:
        all_news = []
        
        # 1. Google News - Split into multiple smaller queries
        google_news = GNews(
            language='en',
            country='US',
            period='1d',  # Last 24 hours
            max_results=15,  # Reduced from 30 to improve speed
            exclude_websites=['pinterest.com', 'twitter.com', 'facebook.com', 'instagram.com']
        )
        
        # Split search into multiple smaller queries with more specific K-pop terms
        search_queries = [
            '("K-pop" OR "Kpop") AND ("BTS" OR "방탄소년단" OR "Bangtan") AND (news OR update OR comeback OR release OR concert OR performance OR award)',
            '("K-pop" OR "Kpop") AND ("BLACKPINK" OR "블랙핑크") AND (news OR update OR comeback OR release OR concert OR performance OR award)',
            '("K-pop" OR "Kpop") AND ("NewJeans" OR "뉴진스" OR "SEVENTEEN" OR "세븐틴") AND (news OR update OR comeback OR release OR concert OR performance OR award)',
            '("K-pop" OR "Kpop") AND ("TWICE" OR "트와이스" OR "IVE" OR "아이브") AND (news OR update OR comeback OR release OR concert OR performance OR award)',
            '("K-pop" OR "Kpop") AND ("Stray Kids" OR "스트레이 키즈" OR "LE SSERAFIM" OR "르세라핌") AND (news OR update OR comeback OR release OR concert OR performance OR award)'
        ]

        # Add delay between queries to prevent rate limiting
        for query in search_queries:
            try:
                results = google_news.get_news(query)
                if results:
                    # Filter out non-K-pop news
                    filtered_results = []
                    kpop_keywords = ['k-pop', 'kpop', 'bts', 'blackpink', 'twice', 'newjeans', 
                                   'seventeen', 'stray kids', 'ive', 'le sserafim', '방탄소년단', 
                                   '블랙핑크', '트와이스', '뉴진스', '세븐틴', '스트레이 키즈', 
                                   '아이브', '르세라핌']
                    
                    for article in results:
                        title_lower = article['title'].lower()
                        # Check if title contains any K-pop keywords
                        if any(keyword in title_lower for keyword in kpop_keywords):
                            filtered_results.append(article)
                    
                    all_news.extend(filtered_results)
                time.sleep(1)  # Add 1 second delay between queries
            except Exception as e:
                print(f"Error in Google News query: {str(e)}")
                continue

        # 2. Soompi News with timeout (already K-pop focused)
        try:
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})
            
            # Get news from Soompi's K-pop news section specifically
            soompi_response = session.get(
                'https://www.soompi.com/category/k-pop', 
                timeout=10
            )
            if soompi_response.ok:
                soup = BeautifulSoup(soompi_response.text, 'html.parser')
                soompi_articles = soup.find_all('article', class_='post-item')
                for article in soompi_articles[:5]:
                    title_elem = article.find('h2', class_='title')
                    if not title_elem:
                        continue
                    title = title_elem.text.strip()
                    url = article.find('a')['href']
                    if not url.startswith('http'):
                        url = 'https://www.soompi.com' + url
                    date = article.find('time')['datetime'] if article.find('time') else datetime.now().isoformat()
                    image = article.find('img')['src'] if article.find('img') else None
                    all_news.append({
                        'title': title,
                        'url': url,
                        'published_date': date,
                        'publisher': 'Soompi',
                        'source': 'Soompi K-pop News',
                        'image': image
                    })
        except requests.exceptions.Timeout:
            print("Timeout error fetching from Soompi")
        except requests.exceptions.RequestException as e:
            print(f"Error fetching from Soompi: {str(e)}")
        except Exception as e:
            print(f"Unexpected error fetching from Soompi: {str(e)}")

        # Process and sort news
        now = datetime.now()
        filtered_news = []
        
        for article in all_news:
            try:
                # Handle different date formats
                if isinstance(article, dict):
                    pub_date = None
                    published_date_str = None
                    
                    # Handle Google News format
                    if 'published date' in article:
                        try:
                            pub_date = datetime.strptime(article['published date'], '%a, %d %b %Y %H:%M:%S GMT')
                            published_date_str = article['published date']
                        except ValueError:
                            pass
                    
                    # Handle Soompi format
                    if not pub_date and 'published_date' in article:
                        try:
                            pub_date = datetime.fromisoformat(article['published_date'].replace('Z', '+00:00'))
                            published_date_str = article['published_date']
                        except ValueError:
                            pass
                    
                    # Only include recent articles (last 24 hours)
                    if pub_date and now - pub_date <= timedelta(days=1):
                        filtered_news.append({
                            'title': article['title'],
                            'url': article['url'],
                            'published_date': published_date_str,
                            'timestamp': pub_date.timestamp(),  # Add timestamp for easier sorting
                            'publisher': article.get('publisher', {}).get('title', article.get('source', 'Unknown Source')),
                            'source': article.get('source', 'Google News'),
                            'image': article.get('image', None)
                        })
            except Exception as e:
                print(f"Error processing article: {str(e)}")
                continue

        # Sort by timestamp (newest first)
        filtered_news.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Remove timestamp from final output
        for article in filtered_news:
            article.pop('timestamp', None)

        # Take top 20 most recent news
        filtered_news = filtered_news[:20]

        if filtered_news:
            # Update cache only if we have new articles
            trending_news_cache['data'] = filtered_news
            trending_news_cache['last_updated'] = datetime.now()
        elif not trending_news_cache['data']:
            # Only if cache is empty, initialize with empty list
            trending_news_cache['data'] = []
            trending_news_cache['last_updated'] = datetime.now()

    except Exception as e:
        print(f"Error fetching news: {str(e)}")
        if not trending_news_cache['data']:
            trending_news_cache['data'] = []
            trending_news_cache['last_updated'] = datetime.now()

def update_news_periodically():
    """Update news every hour"""
    while True:
        fetch_trending_kpop_news()
        time.sleep(3600)  # Sleep for 1 hour

# Start the background update thread
update_thread = threading.Thread(target=update_news_periodically, daemon=True)
update_thread.start()

@app.route('/trending-kpop')
def trending_kpop():
    """Render the trending K-pop news page"""
    if not trending_news_cache['data'] or \
       (trending_news_cache['last_updated'] and \
        datetime.now() - trending_news_cache['last_updated'] > timedelta(hours=1)):
        fetch_trending_kpop_news()
    
    return render_template('trending_kpop.html', 
                         news=trending_news_cache['data'],
                         last_updated=trending_news_cache['last_updated'])

@app.route('/api/trending-kpop')
def get_trending_kpop():
    """API endpoint for getting trending news"""
    try:
        if not trending_news_cache['data'] or \
           (trending_news_cache['last_updated'] and \
            datetime.now() - trending_news_cache['last_updated'] > timedelta(hours=1)):
            fetch_trending_kpop_news()
        
        if not trending_news_cache['data']:
            return jsonify({
                'error': 'No news available at the moment. Please try again later.'
            }), 404
        
        return jsonify({
            'news': trending_news_cache['data'],
            'last_updated': trending_news_cache['last_updated'].isoformat() if trending_news_cache['last_updated'] else None
        })
    except Exception as e:
        print(f"Error in /api/trending-kpop: {str(e)}")
        return jsonify({
            'error': 'An error occurred while fetching the news. Please try again later.'
        }), 500

if __name__ == '__main__':
    app.run(debug=True) 