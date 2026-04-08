from flask import Blueprint, jsonify, request
from app.config import Config
import requests
import time
from datetime import datetime, timedelta

news_bp = Blueprint('news', __name__)

# Cache backend global pour stocker les news
news_cache = {
    'data': None,
    'timestamp': None,
    'expires_at': None
}

def fetch_news_from_api():
    """
    Fetch fresh news from SERPApi Google News
    """
    try:
        # Get API key from config
        api_key = Config.NEWS_API
        
        if not api_key:
            return None, 'SERPApi News API key not configured'
        
        # API endpoint - using SERPApi Google News
        url = "https://serpapi.com/search"
        
        # Parameters for Google News search
        params = {
            'engine': 'google_news',
            'api_key': api_key,
            'num': 20  # Number of results
        }
        
        # Headers pour éviter les erreurs HTML
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Make the API request with timeout
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        # Check if request was successful
        if response.status_code != 200:
            # Try to get error information
            try:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                error_msg = error_data.get("error", f"HTTP {response.status_code}")
            except:
                error_msg = f"HTTP {response.status_code} - HTML response received"
            return None, f'API request failed: {error_msg}'
        
        # Vérifier si la réponse contient du HTML (erreur commune)
        content_type = response.headers.get('content-type', '')
        if 'text/html' in content_type:
            return None, 'API returned HTML instead of JSON - check API key or parameters'
        
        # Parse and return the response
        try:
            response_data = response.json()
        except ValueError as e:
            return None, f'Invalid JSON response: {str(e)}'
        
        # Extract news from the SERPApi response structure
        news = []
        if 'news_results' in response_data:
            news = response_data['news_results']
        elif 'error' in response_data:
            return None, f'API Error: {response_data["error"]}'
        
        return news, None
        
    except requests.exceptions.RequestException as e:
        return None, f'Failed to connect to SERPApi: {str(e)}'
        
    except Exception as e:
        return None, f'An unexpected error occurred: {str(e)}'

@news_bp.route('/api/news/trending', methods=['GET'])
def get_trending_news():
    """
    Get current trending news using cache (10-minute intervals)
    """
    global news_cache
    current_time = datetime.now()
    
    try:
        # Vérifier si le cache est valide (moins de 10 minutes)
        if (news_cache['data'] is not None and 
            news_cache['expires_at'] is not None and 
            current_time < news_cache['expires_at']):
            
            print(f"Serving news from cache (expires: {news_cache['expires_at']})")
            return jsonify({
                'success': True,
                'data': news_cache['data'],
                'cached': True,
                'cache_expires_at': news_cache['expires_at'].isoformat(),
                'message': 'Trending news retrieved from cache'
            })
        
        # Cache expiré ou vide, rafraîchir depuis l'API
        print("Cache expired or empty, fetching fresh news from API")
        fresh_news, error = fetch_news_from_api()
        
        if error:
            # Si erreur et cache existe, utiliser le cache même expiré
            if news_cache['data'] is not None:
                print(f"API failed, using expired cache: {error}")
                return jsonify({
                    'success': True,
                    'data': news_cache['data'],
                    'cached': True,
                    'cache_expired': True,
                    'cache_expires_at': news_cache['expires_at'].isoformat(),
                    'message': f'Using cached data (API unavailable: {error})'
                })
            else:
                # Pas de cache disponible
                return jsonify({
                    'error': 'Failed to fetch news',
                    'message': error
                }), 500
        
        # Mettre à jour le cache avec les nouvelles données
        news_cache['data'] = fresh_news
        news_cache['timestamp'] = current_time
        news_cache['expires_at'] = current_time + timedelta(minutes=10)
        
        print(f"Cache updated with fresh news (expires: {news_cache['expires_at']})")
        
        return jsonify({
            'success': True,
            'data': fresh_news,
            'cached': False,
            'cache_expires_at': news_cache['expires_at'].isoformat(),
            'message': 'Trending news retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'error': 'Internal server error',
            'message': f'An unexpected error occurred: {str(e)}'
        }), 500

@news_bp.route('/api/news/test', methods=['GET'])
def test_news_connection():
    """
    Test endpoint to verify the SERPApi key and connection
    """
    try:
        api_key = Config.NEWS_API
        
        if not api_key:
            return jsonify({
                'success': False,
                'message': 'NEWS_API not configured'
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'SERPApi News API key is configured',
            'api_key_preview': api_key[:10] + '...' if len(api_key) > 10 else api_key
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500

@news_bp.route('/api/news/cache-status', methods=['GET'])
def get_news_cache_status():
    """
    Get current news cache status for debugging
    """
    global news_cache
    current_time = datetime.now()
    
    cache_info = {
        'has_data': news_cache['data'] is not None,
        'timestamp': news_cache['timestamp'].isoformat() if news_cache['timestamp'] else None,
        'expires_at': news_cache['expires_at'].isoformat() if news_cache['expires_at'] else None,
        'is_expired': news_cache['expires_at'] and current_time > news_cache['expires_at'],
        'time_until_expiry': None,
        'data_count': len(news_cache['data']) if news_cache['data'] else 0
    }
    
    if news_cache['expires_at']:
        time_until_expiry = news_cache['expires_at'] - current_time
        cache_info['time_until_expiry'] = str(time_until_expiry)
    
    return jsonify({
        'success': True,
        'cache': cache_info,
        'current_time': current_time.isoformat()
    })

@news_bp.route('/api/news/topics', methods=['GET'])
def extract_topics_from_news():
    """
    Extract trending topics from news articles
    """
    global news_cache
    
    try:
        # Get news from cache or fetch fresh
        if news_cache['data'] is None:
            fresh_news, error = fetch_news_from_api()
            if error:
                return jsonify({
                    'success': False,
                    'message': f'Failed to fetch news: {error}'
                }), 500
            news_cache['data'] = fresh_news
            news_cache['timestamp'] = datetime.now()
            news_cache['expires_at'] = datetime.now() + timedelta(minutes=10)
        
        news_articles = news_cache['data']
        
        if not news_articles:
            return jsonify({
                'success': False,
                'message': 'No news articles available'
            }), 404
        
        # Extract topics from news
        topics = []
        keywords_seen = set()
        
        for article in news_articles[:10]:  # Top 10 articles
            title = article.get('title', '')
            source = article.get('source', {}).get('name', 'Unknown')
            
            # Extract keywords from title
            words = title.lower().split()
            important_words = []
            
            for word in words:
                # Skip common words
                if len(word) < 4 or word in ['the', 'and', 'or', 'but', 'for', 'with', 'this', 'that', 'from', 'have', 'will', 'would', 'could', 'should']:
                    continue
                
                # Clean word
                clean_word = word.strip('.,!?()[]{}"\'')
                if clean_word and clean_word not in keywords_seen:
                    keywords_seen.add(clean_word)
                    important_words.append(clean_word.capitalize())
            
            if important_words:
                topics.append({
                    'title': title,
                    'source': source,
                    'keywords': important_words[:3],  # Top 3 keywords
                    'date': article.get('date', ''),
                    'link': article.get('link', ''),
                    'thumbnail': article.get('thumbnail', ''),
                    'relevance_score': len(important_words) * 10  # Simple scoring
                })
        
        # Sort by relevance score
        topics.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        return jsonify({
            'success': True,
            'data': topics,
            'count': len(topics),
            'message': f'Extracted {len(topics)} topics from trending news'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error extracting topics: {str(e)}'
        }), 500
