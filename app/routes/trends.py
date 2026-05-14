from flask import Blueprint, jsonify, request
from app.config import Config
import requests
import time
from datetime import datetime, timedelta

trends_bp = Blueprint('trends', __name__)

# Cache backend global pour stocker les tendances
trends_cache = {
    'data': None,
    'timestamp': None,
    'expires_at': None
}

# Compteur de requêtes API pour le mode essai limité
api_request_count = {
    'date': datetime.now().date(),
    'count': 0,
    'daily_limit': 100,  # Limite d'essai: 100 requêtes par jour
    'trial_mode': True  # Mode essai activé
}

def fetch_trends_from_api():
    """
    Fetch fresh trends from Twitter API with trial limit management
    """
    global api_request_count
    
    try:
        # Vérifier le mode essai et la limite quotidienne
        current_date = datetime.now().date()
        
        # Réinitialiser le compteur si nouveau jour
        if api_request_count['date'] != current_date:
            api_request_count['date'] = current_date
            api_request_count['count'] = 0
            print(f"Nouveau jour: compteur réinitialisé. Limite quotidienne: {api_request_count['daily_limit']}")
        
        # Vérifier si la limite est atteinte
        if api_request_count['count'] >= api_request_count['daily_limit']:
            print(f"Limite d'essai atteinte: {api_request_count['count']}/{api_request_count['daily_limit']}")
            return None, f'Trial limit reached ({api_request_count["count"]}/{api_request_count["daily_limit"]}) - Please upgrade to full version'
        
        # Get API key from config
        api_key = Config.TREND_API
        
        if not api_key:
            return None, 'Twitter Trends API key not configured'
        
        # API endpoint - using correct TwitterAPI.io endpoint with woeid parameter
        # Using woeid=1 for worldwide trends
        url = "https://api.twitterapi.io/twitter/trends?woeid=1"
        
        # Headers with API key
        headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        
        # Make API request with timeout
        response = requests.get(url, headers=headers, timeout=10)
        
        # Incrémenter le compteur de requêtes
        api_request_count['count'] += 1
        print(f"Requête API #{api_request_count['count']}/{api_request_count['daily_limit']} du jour")
        print(f"API Response Status: {response.status_code}")
        
        # Check if request was successful
        if response.status_code != 200:
            error_data = {}
            try:
                error_data = response.json()
            except:
                error_data = {'error': response.text}
            print(f"API Error: {error_data}")
            return None, f'API request failed with status {response.status_code}: {error_data.get("message", str(error_data))}'
        
        # Parse and return response
        response_data = response.json()
        print(f"API Response: {response_data}")
        
        # Extract trends from TwitterAPI.io response structure
        trends = []
        if response_data.get('status') == 'success' and 'trends' in response_data:
            trends = response_data['trends']
        elif isinstance(response_data, list):
            # Handle if response is directly a list of trends
            trends = response_data
        elif 'data' in response_data:
            # Handle alternate response format
            trends = response_data['data']
        else:
            # If trends found anywhere in response
            trends = response_data.get('trends', [])
        
        return trends, None
        
    except requests.exceptions.RequestException as e:
        print(f"Request Exception: {str(e)}")
        return None, f'Failed to connect to Twitter Trends API: {str(e)}'
        
    except Exception as e:
        print(f"Exception: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, f'An unexpected error occurred: {str(e)}'

@trends_bp.route('/api/trends/twitter', methods=['GET'])
def get_twitter_trends():
    """
    Get current Twitter trends using cache (24-hour intervals) with trial limit
    """
    global trends_cache, api_request_count
    current_time = datetime.now()
    
    try:
        # Vérifier si le cache est valide (moins de 10 minutes)
        if (trends_cache['data'] is not None and 
            trends_cache['expires_at'] is not None and 
            current_time < trends_cache['expires_at']):
            
            print(f"Serving trends from cache (expires: {trends_cache['expires_at']})")
            return jsonify({
                'success': True,
                'data': trends_cache['data'],
                'cached': True,
                'cache_expires_at': trends_cache['expires_at'].isoformat(),
                'message': 'Twitter trends retrieved from cache',
                'trial_mode': api_request_count['trial_mode'],
                'api_requests_today': api_request_count['count'],
                'daily_limit': api_request_count['daily_limit'],
                'remaining_requests': max(0, api_request_count['daily_limit'] - api_request_count['count'])
            })
        
        # Cache expiré ou vide, rafraîchir depuis l'API
        print("Cache expired or empty, fetching fresh trends from API")
        fresh_trends, error = fetch_trends_from_api()
        
        if error:
            print(f"API Error occurred: {error}")
            # Si erreur et cache existe, utiliser le cache même expiré
            if trends_cache['data'] is not None:
                print(f"API failed, using expired cache: {error}")
                return jsonify({
                    'success': True,
                    'data': trends_cache['data'],
                    'cached': True,
                    'cache_expired': True,
                    'cache_expires_at': trends_cache['expires_at'].isoformat() if trends_cache['expires_at'] else None,
                    'message': f'Using cached data (API unavailable: {error})'
                })
            else:
                # Pas de cache disponible - return mock data or error
                print("No cache available, returning error")
                return jsonify({
                    'success': False,
                    'error': 'Failed to fetch trends',
                    'message': error,
                    'data': []  # Return empty array as fallback
                }), 200  # Return 200 instead of 500 to avoid breaking UI
        
        # Mettre à jour le cache avec les nouvelles données
        trends_cache['data'] = fresh_trends if fresh_trends else []
        trends_cache['timestamp'] = current_time
        trends_cache['expires_at'] = current_time + timedelta(hours=24)  # 24 heures
        
        print(f"Cache updated with fresh trends (expires: {trends_cache['expires_at']})")
        
        return jsonify({
            'success': True,
            'data': fresh_trends if fresh_trends else [],
            'cached': False,
            'cache_expires_at': trends_cache['expires_at'].isoformat(),
            'message': 'Twitter trends retrieved successfully',
            'trial_mode': api_request_count['trial_mode'],
            'api_requests_today': api_request_count['count'],
            'daily_limit': api_request_count['daily_limit'],
            'remaining_requests': max(0, api_request_count['daily_limit'] - api_request_count['count'])
        })
        
    except Exception as e:
        print(f"Exception in get_twitter_trends: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Internal server error',
            'message': f'An unexpected error occurred: {str(e)}',
            'data': []
        }), 200  # Return 200 instead of 500

@trends_bp.route('/api/trends/test', methods=['GET'])
def test_trends_connection():
    """
    Test endpoint to verify the API key and connection
    """
    try:
        api_key = Config.TREND_API
        
        if not api_key:
            return jsonify({
                'success': False,
                'message': 'TREND_API not configured'
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'Trends API key is configured',
            'api_key_preview': api_key[:10] + '...' if len(api_key) > 10 else api_key
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500

@trends_bp.route('/api/trends/cache-status', methods=['GET'])
def get_cache_status():
    """
    Get current cache status for debugging
    """
    global trends_cache
    current_time = datetime.now()
    
    cache_info = {
        'has_data': trends_cache['data'] is not None,
        'timestamp': trends_cache['timestamp'].isoformat() if trends_cache['timestamp'] else None,
        'expires_at': trends_cache['expires_at'].isoformat() if trends_cache['expires_at'] else None,
        'is_expired': trends_cache['expires_at'] and current_time > trends_cache['expires_at'],
        'time_until_expiry': None,
        'data_count': len(trends_cache['data']) if trends_cache['data'] else 0
    }
    
    if trends_cache['expires_at']:
        time_until_expiry = trends_cache['expires_at'] - current_time
        cache_info['time_until_expiry'] = str(time_until_expiry)
    
    return jsonify({
        'success': True,
        'cache': cache_info,
        'current_time': current_time.isoformat()
    })
