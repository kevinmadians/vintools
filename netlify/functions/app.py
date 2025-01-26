from flask import Flask
import sys
import os

# Add the root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app import app

def handler(event, context):
    """Netlify function handler to process requests"""
    
    # Get HTTP method and path from the event
    http_method = event['httpMethod']
    path = event['path']
    
    # Prepare the environment for Flask
    environ = {
        'REQUEST_METHOD': http_method,
        'PATH_INFO': path,
        'QUERY_STRING': event.get('queryStringParameters', {}),
        'CONTENT_LENGTH': len(event.get('body', '')),
        'CONTENT_TYPE': event['headers'].get('content-type', ''),
        'HTTP': 'on',
        'wsgi.version': (1, 0),
        'wsgi.input': event.get('body', ''),
        'wsgi.errors': sys.stderr,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
    }
    
    # Handle the request through Flask
    response = app(environ)
    
    return {
        'statusCode': response.status_code,
        'headers': dict(response.headers),
        'body': response.get_data(as_text=True)
    } 