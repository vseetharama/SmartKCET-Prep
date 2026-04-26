"""
ExamForge AI — RAG Backend (Standalone)
Run: python app.py
Then update frontend endpoint to: http://localhost:8000
"""

import warnings
warnings.filterwarnings('ignore', category=FutureWarning)

import re, json, uuid, io
import numpy as np
import cv2
import fitz
import faiss
import pytesseract
from PIL import Image
from docx import Document as DocxDocument
import nest_asyncio
from groq import Groq
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from sentence_transformers import SentenceTransformer
import uvicorn
import asyncio
import subprocess
import os
import socket
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

nest_asyncio.apply()

# Configuration - Load API key from system environment variable
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
if not GROQ_API_KEY:
    raise ValueError('GROQ_API_KEY environment variable is not set. Please set it before running the app.')
groq_client = Groq(api_key=GROQ_API_KEY)
embedder = SentenceTransformer('all-MiniLM-L6-v2')

# Vector Store
class VectorStore:
    def __init__(self):
        self.index = None
        self.chunks = []
        self.dim = 384
    
    def reset(self):
        self.index = faiss.IndexFlatL2(self.dim)
        self.chunks = []
    
    def add(self, texts):
        if self.index is None: 
            self.reset()
        vecs = embedder.encode(texts, show_progress_bar=False).astype('float32')
        self.index.add(vecs)
        self.chunks.extend(texts)
    
    def search(self, query, k=20):
        if not self.chunks: 
            return []
        vec = embedder.encode([query]).astype('float32')
        k = min(k, len(self.chunks))
        _, ids = self.index.search(vec, k)
        return [self.chunks[i] for i in ids[0] if i < len(self.chunks)]

store = VectorStore()

# Text Processing
def preprocess_for_ocr(img):
    try:
        img_np = np.array(img.convert('RGB'))
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        gray = cv2.fastNlMeansDenoising(gray, h=10)
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
        return Image.fromarray(thresh)
    except Exception as e:
        print(f'OCR preprocessing failed: {e}')
        return img

def extract_text_from_pdf(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype='pdf')
    pages = []
    for page in doc:
        text = page.get_text().strip()
        if len(text) > 50:
            pages.append(text)
        else:
            try:
                pix = page.get_pixmap(dpi=400)
                img = Image.open(io.BytesIO(pix.tobytes('png')))
                img = preprocess_for_ocr(img)
                try:
                    ocr_text = pytesseract.image_to_string(img, lang='eng', config='--psm 6 --oem 3')
                    if ocr_text.strip():
                        pages.append(ocr_text)
                except:
                    pass
            except Exception as e:
                print(f'PDF page processing failed: {e}')
    return '\n'.join(pages)

def extract_text_from_docx(file_bytes):
    doc = DocxDocument(io.BytesIO(file_bytes))
    return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())

def extract_text_from_txt(file_bytes):
    return file_bytes.decode('utf-8', errors='ignore')

def chunk_text(text, size=400, overlap=80):
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunks.append(' '.join(words[i:i+size]))
        i += size - overlap
    return [c for c in chunks if len(c.strip()) > 30]

def parse_llm_json(raw):
    original = raw
    raw = raw.strip()
    raw = re.sub(r'^```(?:json|)\n?', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\n?```$', '', raw)
    try:
        data = json.loads(raw)
        if isinstance(data, list): return data
        if isinstance(data, dict) and 'questions' in data: return data['questions']
    except json.JSONDecodeError as e:
        print(f"Direct JSON parse failed: {e}")
    try:
        match = re.search(r'\[\s*\{.*?\}\s*\]', original, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if isinstance(data, list): return data
    except:
        pass
    print("Failed to parse JSON completely.")
    return []

def generate_mcq_set(context_chunks, subject, set_label, used_questions):
    context = '\n\n'.join(context_chunks[:8])
    used_str = '\n'.join(f'- {q}' for q in list(used_questions)[:20]) if used_questions else 'None'

    prompt = f"""You are creating a 20-question MCQ exam paper (Set {set_label}) for: {subject}.

Below is the actual content from uploaded question papers. Use ONLY these topics:
---
{context}
---

Questions already used in other sets (DO NOT repeat these):
{used_str}

RULES:
- Generate EXACTLY 20 MCQ questions
- Each question must have exactly 4 options
- Base questions ONLY on topics from the source content above
- Do NOT repeat any question from the used list
- ans must be the integer index of the correct option (0, 1, 2, or 3)
- Each question is worth 1 mark

Output ONLY a valid JSON array of exactly 20 items. Each item:
{{"q":"question text","type":"MCQ","topic":"topic name","opts":["option A","option B","option C","option D"],"ans":0,"marks":1}}"""

    try:
        resp = groq_client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.5,
            max_tokens=4096,
        )
        questions = parse_llm_json(resp.choices[0].message.content)
    except Exception as e:
        print(f"Error calling Groq API: {e}")
        questions = []
    
    valid_questions = []
    for i, q in enumerate(questions):
        if not isinstance(q, dict) or 'q' not in q or 'opts' not in q or 'ans' not in q:
            continue
        q['id'] = f"{set_label}-{len(valid_questions)}"
        q['type'] = q.get('type', 'MCQ')
        q['marks'] = q.get('marks', 1)
        used_questions.add(q.get('q', ''))
        valid_questions.append(q)
    return valid_questions[:20]

# FastAPI App
app = FastAPI(title='ExamForge Backend')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

@app.get('/health')
def health():
    return {'status': 'ok', 'chunks_indexed': len(store.chunks)}

@app.get('/debug')
def debug():
    return {'chunks_indexed': len(store.chunks), 'sample': store.chunks[:2]}

@app.post('/upload')
async def upload(files: List[UploadFile] = File(...)):
    if len(files) > 10:
        raise HTTPException(400, 'Maximum 10 files allowed')
    store.reset()
    doc_ids, total_chunks = [], 0
    for f in files:
        content = await f.read()
        name = f.filename.lower()
        if name.endswith('.pdf'):
            text = extract_text_from_pdf(content)
        elif name.endswith('.docx'):
            text = extract_text_from_docx(content)
        elif name.endswith(('.txt', '.doc')):
            text = extract_text_from_txt(content)
        else:
            continue
        chunks = chunk_text(text)
        store.add(chunks)
        total_chunks += len(chunks)
        doc_ids.append(str(uuid.uuid4()))
        print(f'✓ Indexed {f.filename}: {len(chunks)} chunks')
    return {'success': True, 'doc_ids': doc_ids, 'total_chunks': total_chunks,
            'message': f'{len(doc_ids)} files indexed with {total_chunks} chunks'}

class GenerateRequest(BaseModel):
    difficulty: str = 'medium'
    count: int = 20
    types: list = ['MCQ']
    subject: str = 'General Subject'
    num_sets: int = 4

@app.post('/generate')
def generate(req: GenerateRequest):
    if not store.chunks:
        raise HTTPException(400, 'No documents uploaded yet.')
    subject = req.subject
    if subject == 'General Subject':
        try:
            sample = ' '.join(store.chunks[:5])
            resp = groq_client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role':'user','content':f'What subject is this exam paper about? Reply with just the subject name, nothing else.\n{sample[:500]}'}],
                temperature=0.1, max_tokens=20
            )
            subject = resp.choices[0].message.content.strip()
        except:
            pass
    print(f'Generating for subject: {subject}')
    used_questions = set()
    sets = []
    for label in ['A', 'B', 'C', 'D']:
        chunks = store.search(f'{subject} multiple choice questions', k=20)
        questions = generate_mcq_set(chunks, subject, label, used_questions)
        sets.append(questions)
        print(f'✓ Set {label}: {len(questions)} questions')
    return {'sets': sets}

class AnalyzeRequest(BaseModel):
    questions: list
    answers: dict
    student: dict = {}

@app.post('/analyze')
def analyze(req: AnalyzeRequest):
    total, earned = 0, 0
    topic_scores, type_scores, results = {}, {}, []
    for i, q in enumerate(req.questions):
        m = 1
        total += m
        topic = q.get('topic', 'General')
        topic_scores.setdefault(topic, {'earned': 0, 'total': 0})['total'] += m
        type_scores.setdefault('MCQ', {'earned': 0, 'total': 0})['total'] += m
        given = req.answers.get(str(i))
        e, status = 0, 'wrong'
        if given is None or given == '': 
            status = 'unanswered'
        elif str(given) == str(q.get('ans')): 
            e, status = m, 'correct'
        earned += e
        topic_scores[topic]['earned'] += e
        type_scores['MCQ']['earned'] += e
        results.append({'q': q.get('q'), 'type': 'MCQ', 'topic': topic,
                        'given': given, 'correctAns': q.get('ans'),
                        'earned': e, 'marks': m, 'status': status})
    pct = round((earned / total) * 100) if total else 0
    strong, can_improve, weak = [], [], []
    for t, s in topic_scores.items():
        p = round((s['earned'] / s['total']) * 100) if s['total'] else 0
        (strong if p >= 70 else can_improve if p >= 40 else weak).append({'topic': t, 'pct': p})
    rec = 'Excellent! ' if pct >= 75 else 'Good effort. ' if pct >= 50 else 'Needs improvement. '
    if weak: 
        rec += f"Focus on: {', '.join(w['topic'] for w in weak)}."
    return {'percentage': pct, 'earned': earned, 'total': total,
            'topicScores': topic_scores, 'typeScores': type_scores,
            'strong': strong, 'canImprove': can_improve, 'weak': weak,
            'questionResults': results, 'pass': pct >= 40, 'recommendation': rec}

if __name__ == '__main__':
    port = 8000
    # Kill existing process if any
    try:
        result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if f':{port}' in line:
                pid = line.split()[-1]
                if pid.isdigit():
                    os.system(f'taskkill /PID {pid} /F 2>nul')
                break
    except:
        pass
    
    print(f"\n{'=' * 60}")
    print("🚀 ExamForge Backend Starting")
    print(f"{'=' * 60}")
    print(f"Server: http://localhost:{port}")
    print(f"Health: http://localhost:{port}/health")
    print(f"{'=' * 60}\n")
    
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')
