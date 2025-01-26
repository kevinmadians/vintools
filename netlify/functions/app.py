from flask import Flask, Response
import sys
import os
import json
from base64 import b64encode
from io import BytesIO

# Add the root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app import app

def create_environ(event):
    """Create WSGI environment from Lambda event"""
    body = event.get('body', '')
    if body and isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            pass

    headers = event.get('headers', {}) or {}
    query_params = event.get('queryStringParameters', {}) or {}
    query_string = '&'.join([f"{k}={v}" for k, v in query_params.items()]) if query_params else ''
    
    if isinstance(body, dict):
        body = json.dumps(body).encode('utf-8')
    elif isinstance(body, str):
        body = body.encode('utf-8')
    else:
        body = b''
    
    environ = {
        'REQUEST_METHOD': event['httpMethod'],
        'SCRIPT_NAME': '',
        'PATH_INFO': event['path'],
        'QUERY_STRING': query_string,
        'CONTENT_TYPE': headers.get('content-type', 'application/json'),
        'CONTENT_LENGTH': str(len(body)),
        'SERVER_NAME': headers.get('host', 'localhost'),
        'SERVER_PORT': '443',
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': 'https',
        'wsgi.input': BytesIO(body),
        'wsgi.errors': sys.stderr,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
    }

    # Add HTTP headers
    for header, value in headers.items():
        key = 'HTTP_' + header.upper().replace('-', '_')
        if key not in ('HTTP_CONTENT_TYPE', 'HTTP_CONTENT_LENGTH'):
            environ[key] = value

    return environ

def handler(event, context):
    """Netlify function handler to process requests"""
    
    # Create WSGI environment
    environ = create_environ(event)
    
    # Variables to store response data
    response_data = []
    response_headers = []
    response_status = []

    def start_response(status, headers):
        response_status.append(status)
        response_headers.extend(headers)

    # Get response from Flask app
    try:
        resp = app(environ, start_response)
        response_data = b''.join(resp)
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)}),
            'headers': {'Content-Type': 'application/json'}
        }

    # Convert response data to string if possible
    try:
        response_body = response_data.decode('utf-8')
        is_base64 = False
    except (UnicodeDecodeError, AttributeError):
        response_body = b64encode(response_data).decode('utf-8')
        is_base64 = True

    # Convert headers to dictionary
    headers_dict = {}
    for key, value in response_headers:
        headers_dict[key] = value

    # Ensure JSON content type for /scrape endpoint
    if environ['PATH_INFO'].endswith('/scrape'):
        headers_dict['Content-Type'] = 'application/json'

    # Parse status code
    status_code = int(response_status[0].split()[0])

    return {
        'statusCode': status_code,
        'headers': headers_dict,
        'body': response_body,
        'isBase64Encoded': is_base64
    } 