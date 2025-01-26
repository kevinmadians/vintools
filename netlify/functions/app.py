import json
from newspaper import Article
import re

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

def handler(event, context):
    """Simple serverless function to handle article scraping"""
    
    # Handle OPTIONS request for CORS
    if event['httpMethod'] == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
            },
            'body': ''
        }
    
    # Only handle POST requests to /scrape
    if not (event['httpMethod'] == 'POST' and event['path'].endswith('/scrape')):
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Not found'})
        }
    
    # Parse request body
    try:
        body = json.loads(event.get('body', '{}'))
        url = body.get('url')
        
        if not url:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'URL is required'})
            }
        
        # Scrape the article
        article = Article(url)
        article.download()
        article.parse()
        
        # Get the title and main text content
        title = article.title
        text = article.text
        
        if not title or not text:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Could not extract content from the provided URL.'})
            }
        
        # Clean the article content
        cleaned_text = clean_article_text(text)
        
        if not cleaned_text:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'No usable content found after cleaning the article.'})
            }
        
        # Add title at the beginning
        full_article = f"{title}\n\n{cleaned_text}"
        
        # Return success response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'POST, OPTIONS'
            },
            'body': json.dumps({
                'text': full_article,
                'url': url,
                'title': title
            })
        }
        
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Invalid JSON in request body'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': f'Server error: {str(e)}'})
        } 