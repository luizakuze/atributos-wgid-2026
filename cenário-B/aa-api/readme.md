# AA API
 
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt 
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

curl http://localhost:8000/attributes/bob