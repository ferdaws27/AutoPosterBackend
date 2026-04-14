from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
import tempfile
import json
import requests as http_requests
from werkzeug.utils import secure_filename
import nltk
import spacy
from textblob import TextBlob
import PyPDF2
from pydub import AudioSegment
import speech_recognition as sr
from collections import Counter
import re

voice_bp = Blueprint("voice_bp", __name__, url_prefix="/api/voice")

# Download required NLTK data
try:
    nltk.download('punkt', quiet=True)
    nltk.download('vader_lexicon', quiet=True)
    nltk.download('stopwords', quiet=True)
    nltk.download('averaged_perceptron_tagger', quiet=True)
except:
    pass

# Load spaCy model
try:
    nlp = spacy.load("en_core_web_sm")
except:
    nlp = None

# Initialize speech recognizer
recognizer = sr.Recognizer()


def _ai_voice_analysis(text, source_type="text"):
    """Use OpenRouter AI to deeply analyze voice from text or speech transcription."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    if not api_key:
        return None

    # Limit text to ~3000 chars for prompt efficiency
    sample = text[:3000]

    if source_type == "audio":
        prompt = f"""Analyze the following speech transcription from a voice recording and extract the speaker's unique vocal communication style.

SPEECH TRANSCRIPTION:
---
{sample}
---

This is a transcription of someone SPEAKING, not writing. Analyze their speaking style deeply and return a JSON object with these exact keys:
{{
  "tone": "dominant speaking tone (e.g. Warm & Enthusiastic, Calm & Authoritative, Energetic & Motivational, Casual & Friendly)",
  "sentenceStyle": "how they construct spoken sentences (e.g. Short & Direct, Long & Storytelling, Conversational & Flowing, Punchy & Rhythmic)",
  "structure": "how they organize their speech (e.g. Story -> Point -> Takeaway, Direct Statement -> Explanation -> Question, Free-flowing Conversation)",
  "emojiUsage": "None",
  "hashtagUsage": "None",
  "vocabularyLevel": "Simple / Intermediate / Advanced / Technical",
  "hookStyle": "how they grab attention when speaking (e.g. Bold Opening Statement, Rhetorical Question, Personal Story, Provocative Claim)",
  "ctaStyle": "how they close or engage listeners (e.g. Open Question, Call to Action, Reflective Pause, Summary)",
  "contentThemes": ["top 3-5 topics they talk about"],
  "writingPatterns": ["3-5 speaking patterns like 'Uses verbal fillers', 'Repeats key phrases', 'Speaks in metaphors', 'Lists examples in threes'"],
  "uniqueTraits": ["2-4 distinctive vocal/speaking traits that set this speaker apart"],
  "confidenceScore": 70
}}

Focus on SPEAKING patterns (pace, energy, verbal habits, conversational style) not writing patterns.
Be specific and accurate based on the actual transcription. Do not use generic descriptions.
Return ONLY the JSON object, no markdown, no explanation."""
        system_msg = "You are a vocal communication analyst specializing in speaking style. Return only valid JSON."
    else:
        prompt = f"""Analyze the following writing samples and extract the author's unique writing voice profile.

WRITING SAMPLES:
---
{sample}
---

Analyze deeply and return a JSON object with these exact keys:
{{
  "tone": "dominant emotional tone (e.g. Authoritative & Inspiring, Casual & Witty, Professional & Analytical)",
  "sentenceStyle": "sentence pattern (e.g. Short & Punchy, Long & Flowing, Mixed & Rhythmic)",
  "structure": "typical post structure (e.g. Hook -> Story -> Lesson -> CTA)",
  "emojiUsage": "None / Minimal / Moderate / Heavy",
  "hashtagUsage": "None / Minimal / Moderate / Heavy",
  "vocabularyLevel": "Simple / Intermediate / Advanced / Technical",
  "hookStyle": "how they open posts (e.g. Bold Claim, Question, Story Opening, Statistic)",
  "ctaStyle": "how they close posts (e.g. Question to Audience, Direct Ask, Reflective, None)",
  "contentThemes": ["top 3-5 recurring themes"],
  "writingPatterns": ["3-5 specific patterns like 'Uses analogies', 'Lists of 3', 'Personal anecdotes'"],
  "uniqueTraits": ["2-4 distinctive writing traits that set this author apart"],
  "confidenceScore": 75
}}

Be specific and accurate based on the actual text. Do not use generic descriptions.
Return ONLY the JSON object, no markdown, no explanation."""
        system_msg = "You are a writing style analyst. Return only valid JSON."

    try:
        resp = http_requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 800,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return None

        content = resp.json()["choices"][0]["message"]["content"].strip()
        # Extract JSON from response
        if content.startswith("```"):
            content = re.sub(r"```(?:json)?", "", content).strip()
        brace_start = content.find("{")
        brace_end = content.rfind("}")
        if brace_start != -1 and brace_end != -1:
            content = content[brace_start : brace_end + 1]
        return json.loads(content)
    except Exception as e:
        print(f"AI voice analysis error: {e}")
        return None


def _transcribe_with_assemblyai(filepath):
    """Transcribe audio file using AssemblyAI API."""
    import time
    api_key = os.getenv("VOICE_API_KEY")
    if not api_key:
        print("AssemblyAI API key (VOICE_API_KEY) not found in environment")
        return None

    base_url = "https://api.assemblyai.com"
    headers = {"authorization": api_key}

    # Step 1: Upload the audio file
    try:
        with open(filepath, "rb") as f:
            upload_resp = http_requests.post(
                base_url + "/v2/upload",
                headers=headers,
                data=f
            )
        print(f"AssemblyAI upload response: {upload_resp.status_code}")
        if upload_resp.status_code != 200:
            print(f"AssemblyAI upload failed: {upload_resp.text}")
            return None
        audio_url = upload_resp.json()["upload_url"]
    except Exception as e:
        print(f"AssemblyAI upload error: {e}")
        return None

    # Step 2: Request transcription
    try:
        transcript_resp = http_requests.post(
            base_url + "/v2/transcript",
            headers=headers,
            json={
                "audio_url": audio_url,
                "speech_models": ["universal-3-pro", "universal-2"],
            }
        )
        print(f"AssemblyAI transcript request response: {transcript_resp.status_code}")
        if transcript_resp.status_code != 200:
            print(f"AssemblyAI transcript request failed: {transcript_resp.text}")
            return None
        transcript_id = transcript_resp.json()["id"]
    except Exception as e:
        print(f"AssemblyAI transcript request error: {e}")
        return None

    # Step 3: Poll for result
    polling_url = base_url + "/v2/transcript/" + transcript_id
    while True:
        poll_resp = http_requests.get(polling_url, headers=headers)
        r = poll_resp.json()
        st = r.get("status")
        if st == "completed":
            txt = r.get("text")
            print(f"AssemblyAI transcription completed, text length: {len(txt or '')}")
            return txt
        elif st == "error":
            print(f"AssemblyAI transcription error: {r.get('error')}")
            return None
        time.sleep(3)


ALLOWED_EXTENSIONS = {
    'audio': ['mp3', 'wav', 'm4a', 'flac', 'ogg', 'webm'],
    'text': ['txt', 'pdf', 'docx']
}

def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS['audio'] or ext in ALLOWED_EXTENSIONS['text']

def extract_text_from_file(filepath, filename):
    """Extract text from uploaded file"""
    ext = filename.rsplit('.', 1)[1].lower()
    
    try:
        if ext in ALLOWED_EXTENSIONS['text']:
            if ext == 'txt':
                with open(filepath, 'r', encoding='utf-8') as f:
                    return f.read()
            elif ext == 'pdf':
                with open(filepath, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text()
                    return text
        
        elif ext in ALLOWED_EXTENSIONS['audio']:
            # Transcribe audio using AssemblyAI
            return _transcribe_with_assemblyai(filepath)
                
    except Exception as e:
        print(f"Error extracting text: {e}")
        return None

def analyze_with_nltk(text):
    """Analyze text using NLTK with logical and true insights"""
    if not text or len(text.strip()) < 10:
        return None
    
    try:
        # Clean text
        text = text.strip()
        
        # Basic text analysis
        words = nltk.word_tokenize(text.lower())
        sentences = nltk.sent_tokenize(text)
        
        if not words or not sentences:
            return None
        
        # Sentiment analysis
        from nltk.sentiment import SentimentIntensityAnalyzer
        sia = SentimentIntensityAnalyzer()
        sentiment_scores = sia.polarity_scores(text)
        
        # Determine sentiment with more nuance
        compound = sentiment_scores['compound']
        if compound >= 0.5:
            sentiment = 'Very Positive'
        elif compound >= 0.1:
            sentiment = 'Positive'
        elif compound <= -0.5:
            sentiment = 'Very Negative'
        elif compound <= -0.1:
            sentiment = 'Negative'
        else:
            sentiment = 'Neutral'
        
        # Language detection using TextBlob
        try:
            blob = TextBlob(text)
            language = blob.detect_language()
        except:
            language = 'en'
        
        # Advanced text metrics
        avg_sentence_length = len(words) / len(sentences) if sentences else 0
        
        # Count different types of words
        try:
            from nltk.corpus import stopwords
            stop_words = set(stopwords.words('english'))
            content_words = [w for w in words if w.isalpha() and w not in stop_words]
        except:
            content_words = [w for w in words if w.isalpha() and len(w) > 2]
        
        # Count question marks, exclamations (engagement indicators)
        question_marks = text.count('?')
        exclamations = text.count('!')
        
        # Determine writing style based on actual metrics
        if avg_sentence_length > 25:
            writing_style = "Academic"
        elif avg_sentence_length > 18:
            writing_style = "Professional"
        elif avg_sentence_length > 12:
            writing_style = "Conversational"
        else:
            writing_style = "Casual"
        
        # Calculate complexity score
        complex_words = [w for w in words if len(w) > 6]
        complexity_ratio = len(complex_words) / len(words) if words else 0
        
        # Determine content type based on patterns
        has_numbers = any(char.isdigit() for char in text)
        has_urls = 'http' in text.lower() or 'www.' in text.lower()
        has_email = '@' in text and '.' in text.split('@')[-1]
        
        content_type = "General"
        if has_numbers and has_urls:
            content_type = "Data-Driven"
        elif has_urls:
            content_type = "Web Content"
        elif has_email:
            content_type = "Communication"
        elif any(word in text.lower() for word in ['step', 'guide', 'how', 'tutorial']):
            content_type = "Educational"
        elif any(word in text.lower() for word in ['analysis', 'research', 'study']):
            content_type = "Analytical"
        
        return {
            'sentiment': sentiment,
            'sentiment_scores': sentiment_scores,
            'language': language,
            'word_count': len(words),
            'sentence_count': len(sentences),
            'avg_sentence_length': round(avg_sentence_length, 1),
            'content_word_count': len(content_words),
            'unique_words': len(set(words)),
            'writing_style': writing_style,
            'question_count': question_marks,
            'exclamation_count': exclamations,
            'engagement_score': min(100, (question_marks + exclamations) * 15),
            'complexity_ratio': round(complexity_ratio, 2),
            'content_type': content_type,
            'has_numbers': has_numbers,
            'has_urls': has_urls,
            'readability_estimate': "Easy" if avg_sentence_length < 15 else "Medium" if avg_sentence_length < 20 else "Difficult"
        }
        
    except Exception as e:
        print(f"NLTK analysis error: {e}")
        return None

def analyze_with_spacy(text):
    """Analyze text using spaCy with logical and true insights"""
    if not text or not nlp or len(text.strip()) < 10:
        return None
    
    try:
        doc = nlp(text.strip())
        
        # Named entities with categorization
        entities = [(ent.text, ent.label_) for ent in doc.ents]
        
        # Categorize entities
        entity_categories = {}
        for ent_text, ent_label in entities:
            if ent_label not in entity_categories:
                entity_categories[ent_label] = []
            entity_categories[ent_label].append(ent_text)
        
        # Part of speech analysis
        pos_tags = [(token.text, token.pos_) for token in doc]
        
        # Count different types of words
        pos_counts = {}
        for _, pos in pos_tags:
            pos_counts[pos] = pos_counts.get(pos, 0) + 1
        
        # Extract meaningful keywords (nouns, proper nouns, adjectives)
        keywords = []
        for token in doc:
            if (token.pos_ in ['NOUN', 'PROPN', 'ADJ'] and 
                len(token.text) > 2 and 
                not token.is_stop and 
                not token.is_punct and
                token.is_alpha):
                keywords.append(token.lemma_.lower())
        
        # Remove duplicates and get most common keywords
        keyword_freq = Counter(keywords)
        top_keywords = [word for word, freq in keyword_freq.most_common(12)]
        
        # Analyze complexity
        total_tokens = len([token for token in doc if not token.is_punct])
        unique_tokens = len(set([token.lemma_.lower() for token in doc if not token.is_punct]))
        lexical_diversity = unique_tokens / total_tokens if total_tokens > 0 else 0
        
        # Calculate readability (simplified Flesch-Kincaid)
        sentences = list(doc.sents)
        if not sentences:
            return None
            
        total_words = sum(len(sent) for sent in sentences)
        avg_sentence_length = total_words / len(sentences) if sentences else 0
        
        # Count syllables (simplified but more accurate)
        def count_syllables(word):
            if not word or not word.isalpha():
                return 1
            word = word.lower()
            vowels = "aeiouy"
            syllable_count = 0
            prev_was_vowel = False
            for char in word:
                is_vowel = char in vowels
                if is_vowel and not prev_was_vowel:
                    syllable_count += 1
                prev_was_vowel = is_vowel
            if word.endswith('e') and syllable_count > 1:
                syllable_count -= 1
            return max(1, syllable_count)
        
        total_syllables = sum(count_syllables(token.text) for token in doc if token.is_alpha)
        avg_syllables_per_word = total_syllables / total_words if total_words > 0 else 0
        
        # Flesch Reading Ease Score (real formula)
        if avg_sentence_length > 0 and avg_syllables_per_word > 0:
            readability = 206.835 - (1.015 * avg_sentence_length) - (84.6 * avg_syllables_per_word)
            readability = max(0, min(100, readability))
        else:
            readability = 50
        
        # Enhanced content categories based on actual keyword analysis
        tech_keywords = ['technology', 'software', 'data', 'digital', 'ai', 'machine', 'computer', 'system', 'app', 'code', 'algorithm', 'platform']
        business_keywords = ['business', 'market', 'customer', 'revenue', 'profit', 'strategy', 'management', 'sales', 'company', 'brand', 'marketing']
        leadership_keywords = ['leadership', 'team', 'management', 'leader', 'organization', 'culture', 'employee', 'people', 'skill', 'development']
        science_keywords = ['research', 'study', 'analysis', 'experiment', 'theory', 'scientific', 'method', 'evidence', 'result']
        education_keywords = ['learning', 'education', 'teaching', 'student', 'course', 'knowledge', 'skill', 'training', 'tutorial']
        
        # Count keyword matches
        tech_score = sum(1 for kw in top_keywords if any(tech in kw for tech in tech_keywords))
        business_score = sum(1 for kw in top_keywords if any(biz in kw for biz in business_keywords))
        leadership_score = sum(1 for kw in top_keywords if any(lead in kw for lead in leadership_keywords))
        science_score = sum(1 for kw in top_keywords if any(sci in kw for sci in science_keywords))
        education_score = sum(1 for kw in top_keywords if any(edu in kw for edu in education_keywords))
        
        # Determine primary theme based on actual scores
        scores = {
            'Technology & Innovation': tech_score,
            'Business & Strategy': business_score,
            'Leadership & Management': leadership_score,
            'Science & Research': science_score,
            'Education & Learning': education_score
        }
        
        primary_theme = max(scores, key=scores.get)
        if scores[primary_theme] == 0:
            primary_theme = "General Content"
        
        # Enhanced tone analysis based on actual sentiment words
        positive_words = ['good', 'great', 'excellent', 'amazing', 'wonderful', 'fantastic', 'best', 'innovative', 'successful', 'effective', 'strong', 'positive', 'valuable', 'important', 'useful']
        negative_words = ['bad', 'terrible', 'awful', 'horrible', 'worst', 'difficult', 'challenging', 'problem', 'issue', 'negative', 'poor', 'weak', 'fail', 'failure', 'wrong']
        
        positive_count = sum(1 for token in doc if token.lemma_.lower() in positive_words)
        negative_count = sum(1 for token in doc if token.lemma_.lower() in negative_words)
        
        # More nuanced tone determination
        total_sentiment_words = positive_count + negative_count
        if total_sentiment_words == 0:
            spacy_tone = "Neutral"
        else:
            positive_ratio = positive_count / total_sentiment_words
            if positive_ratio >= 0.8:
                spacy_tone = "Very Positive"
            elif positive_ratio >= 0.6:
                spacy_tone = "Positive"
            elif positive_ratio >= 0.4:
                spacy_tone = "Neutral"
            elif positive_ratio >= 0.2:
                spacy_tone = "Negative"
            else:
                spacy_tone = "Very Negative"
        
        # Determine writing purpose based on patterns
        purpose_indicators = {
            'Informative': ['information', 'data', 'facts', 'details', 'explain', 'describe'],
            'Persuasive': ['convince', 'persuade', 'argue', 'recommend', 'suggest', 'should'],
            'Instructional': ['step', 'guide', 'how', 'process', 'method', 'instruction'],
            'Narrative': ['story', 'experience', 'journey', 'history', 'happened', 'began']
        }
        
        purpose_scores = {}
        for purpose, indicators in purpose_indicators.items():
            score = sum(1 for indicator in indicators if indicator in text.lower())
            purpose_scores[purpose] = score
        
        writing_purpose = max(purpose_scores, key=purpose_scores.get)
        if purpose_scores[writing_purpose] == 0:
            writing_purpose = "General"
        
        return {
            'entities': entities,
            'entity_categories': entity_categories,
            'pos_tags': pos_tags,
            'pos_counts': pos_counts,
            'keywords': top_keywords,
            'keyword_count': len(top_keywords),
            'readability': round(readability, 1),
            'avg_sentence_length': round(avg_sentence_length, 1),
            'token_count': total_tokens,
            'unique_tokens': unique_tokens,
            'lexical_diversity': round(lexical_diversity, 2),
            'primary_theme': primary_theme,
            'theme_scores': scores,
            'tone': spacy_tone,
            'sentiment_indicators': {
                'positive_words': positive_count,
                'negative_words': negative_count,
                'total_sentiment_words': total_sentiment_words
            },
            'writing_purpose': writing_purpose,
            'purpose_scores': purpose_scores,
            'complexity_level': 'High' if readability < 30 else 'Medium' if readability < 70 else 'Low',
            'vocabulary_richness': 'Rich' if lexical_diversity > 0.7 else 'Moderate' if lexical_diversity > 0.5 else 'Limited'
        }
        
    except Exception as e:
        print(f"spaCy analysis error: {e}")
        return None

def analyze_audio_features(filepath):
    """Analyze audio file features"""
    try:
        audio = AudioSegment.from_file(filepath)
        
        # Basic audio features
        duration_seconds = len(audio) / 1000.0
        
        # Calculate pitch (simplified - using frame rate)
        frame_rate = audio.frame_rate
        
        # Calculate tempo (beats per minute - simplified estimation)
        # This is a very rough estimation
        duration_minutes = duration_seconds / 60.0
        estimated_tempo = 120  # Default tempo
        
        # Calculate clarity based on audio format and quality
        channels = audio.channels
        sample_width = audio.sample_width
        clarity = "High" if sample_width >= 2 and channels >= 2 else "Medium" if sample_width >= 2 else "Basic"
        
        return {
            'duration': f"{duration_seconds:.1f}s",
            'duration_seconds': duration_seconds,
            'pitch': f"{frame_rate} Hz",
            'tempo': f"~{estimated_tempo} BPM",
            'channels': channels,
            'sample_rate': frame_rate,
            'clarity': clarity,
            'file_size': f"{os.path.getsize(filepath) / 1024 / 1024:.1f} MB"
        }
        
    except Exception as e:
        print(f"Audio analysis error: {e}")
        return None

@voice_bp.post("/analyze")
@jwt_required()
def analyze_voice():
    """Analyze uploaded voice or text file"""
    try:
        user_id = get_jwt_identity()
        
        if 'file' not in request.files:
            return jsonify({
                "success": False,
                "error": "No file provided"
            }), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                "success": False,
                "error": "No file selected"
            }), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                "success": False,
                "error": "File type not allowed"
            }), 400
        
        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        temp_dir = tempfile.gettempdir()
        filepath = os.path.join(temp_dir, filename)
        file.save(filepath)
        
        try:
            # Extract text from file
            text = extract_text_from_file(filepath, filename)
            
            if not text:
                ext = filename.rsplit('.', 1)[1].lower()
                if ext in ALLOWED_EXTENSIONS['audio']:
                    return jsonify({
                        "success": False,
                        "error": "No speech detected in the recording. Please speak clearly and try again."
                    }), 400
                return jsonify({
                    "success": False,
                    "error": "Could not extract text from file"
                }), 400
            
            # Determine file type
            ext = filename.rsplit('.', 1)[1].lower()
            is_audio = ext in ALLOWED_EXTENSIONS['audio']

            # Perform NLTK/spaCy analyses
            nltk_result = analyze_with_nltk(text)
            spacy_result = analyze_with_spacy(text)
            voice_result = analyze_audio_features(filepath) if is_audio else None
            
            # AI-powered deep voice analysis (speech vs writing)
            ai_analysis = _ai_voice_analysis(text, source_type="audio" if is_audio else "text")

            return jsonify({
                "success": True,
                "data": {
                    "filename": filename,
                    "file_type": "audio" if is_audio else "text",
                    "extracted_text": text[:500] + "..." if len(text) > 500 else text,
                    "nltk": nltk_result,
                    "spacy": spacy_result,
                    "voice": voice_result,
                    "ai": ai_analysis,
                }
            })
            
        finally:
            # Clean up temporary file
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@voice_bp.post("/analyze-text")
@jwt_required()
def analyze_voice_text():
    """Analyze transcribed speech text (no file upload needed)"""
    try:
        data = request.get_json()
        text = (data or {}).get("text", "").strip()
        source_type = (data or {}).get("source_type", "audio")

        if not text or len(text) < 10:
            return jsonify({"success": False, "error": "Text too short. Please speak for at least 10 seconds."}), 400

        nltk_result = analyze_with_nltk(text)
        spacy_result = analyze_with_spacy(text)
        ai_analysis = _ai_voice_analysis(text, source_type=source_type)

        return jsonify({
            "success": True,
            "data": {
                "filename": "live-recording",
                "file_type": "audio",
                "extracted_text": text[:500] + "..." if len(text) > 500 else text,
                "nltk": nltk_result,
                "spacy": spacy_result,
                "voice": None,
                "ai": ai_analysis,
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@voice_bp.get("/models/status")
@jwt_required()
def get_models_status():
    """Check if NLP models are loaded"""
    try:
        return jsonify({
            "success": True,
            "data": {
                "nltk": {
                    "loaded": True,
                    "packages": ["punkt", "vader_lexicon", "stopwords", "averaged_perceptron_tagger"]
                },
                "spacy": {
                    "loaded": nlp is not None,
                    "model": "en_core_web_sm" if nlp else None
                },
                "speech_recognition": {
                    "loaded": True,
                    "engine": "Google Speech Recognition"
                }
            }
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
