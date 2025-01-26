from flask import Flask, Response, jsonify
import sys
import os
import json
from base64 import b64encode
from io import BytesIO
from newspaper import Article, ArticleException

# Add the root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app import app, clean_article_text

def scrape_article(url):
    """Scrape article content with proper error handling"""
    try:
        if not url or not url.startswith(('http://', 'https://')):
            return jsonify({'error': 'Invalid URL. Please provide a valid HTTP or HTTPS URL.'})
            
        article = Article(url)
        article.download()
        article.parse()
        
        # Get the title and main text content
        title = article.title
        text = article.text
        
        if not title or not text:
            return jsonify({'error': 'Could not extract content from the provided URL.'})
        
        # Clean the article content
        cleaned_text = clean_article_text(text)
        
        if not cleaned_text:
            return jsonify({'error': 'No usable content found after cleaning the article.'})
        
        # Add title at the beginning
        full_article = f"{title}\n\n{cleaned_text}"
        
        return jsonify({
            'text': full_article,
            'url': url,
            'title': title
        })
    except ArticleException as e:
        return jsonify({'error': f'Failed to scrape article: {str(e)}'})
    except Exception as e:
        return jsonify({'error': f'Unexpected error while scraping: {str(e)}'})

def handler(event, context):
    """Netlify function handler to process requests"""
    
    # Special handling for scraping endpoint
    if event['path'].endswith('/scrape') and event['httpMethod'] == 'POST':
        try:
            # Parse the request body
            body = event.get('body', '')
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    return {
                        'statusCode': 400,
                        'headers': {'Content-Type': 'application/json'},
                        'body': json.dumps({'error': 'Invalid JSON in request body'})
                    }
            
            # Get the URL from the request
            url = body.get('url')
            if not url:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({'error': 'URL is required'})
                }
            
            # Directly handle scraping here
            result = scrape_article(url)
            
            # Convert Flask response to Netlify response
            if isinstance(result, Response):
                response_data = json.loads(result.get_data(as_text=True))
                return {
                    'statusCode': result.status_code,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Headers': 'Content-Type',
                        'Access-Control-Allow-Methods': 'POST, OPTIONS'
                    },
                    'body': json.dumps(response_data)
                }
            
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Invalid response from scraper'})
            }
            
        except Exception as e:
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': f'Server error: {str(e)}'})
            }
    
    # Handle other routes through Flask
    try:
        # Create WSGI environment
        environ = {
            'REQUEST_METHOD': event['httpMethod'],
            'SCRIPT_NAME': '',
            'PATH_INFO': event['path'],
            'QUERY_STRING': '',
            'SERVER_NAME': 'netlify',
            'SERVER_PORT': '443',
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'wsgi.version': (1, 0),
            'wsgi.url_scheme': 'https',
            'wsgi.input': BytesIO(event.get('body', '').encode('utf-8')),
            'wsgi.errors': sys.stderr,
            'wsgi.multithread': False,
            'wsgi.multiprocess': False,
            'wsgi.run_once': False,
        }

        # Add headers
        for key, value in event.get('headers', {}).items():
            environ[f'HTTP_{key.upper().replace("-", "_")}'] = value

        # Variables to store response data
        response_data = []
        response_headers = []
        response_status = []

        def start_response(status, headers):
            response_status.append(status)
            response_headers.extend(headers)

        # Get response from Flask app
        resp = app(environ, start_response)
        response_data = b''.join(resp)

        # Convert response data to string if possible
        try:
            response_body = response_data.decode('utf-8')
            is_base64 = False
        except (UnicodeDecodeError, AttributeError):
            response_body = b64encode(response_data).decode('utf-8')
            is_base64 = True

        # Convert headers to dictionary
        headers_dict = dict(response_headers)
        headers_dict['Content-Type'] = 'application/json'
        headers_dict['Access-Control-Allow-Origin'] = '*'
        headers_dict['Access-Control-Allow-Headers'] = 'Content-Type'
        headers_dict['Access-Control-Allow-Methods'] = 'POST, OPTIONS'

        # Parse status code
        status_code = int(response_status[0].split()[0])

        return {
            'statusCode': status_code,
            'headers': headers_dict,
            'body': response_body,
            'isBase64Encoded': is_base64
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        } 