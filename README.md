# 🤖 Chat Support Agent

This project is an AI-powered support chatbot that can run using either **Anthropic** or **OpenAI** models. 

---

## 🧰 Requirements

- Python 3.10+
- Docker (optional)

---

## ⚙️ Environment Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-username/chat-support-agent.git
cd chat-support-agent
```

### 2. Create and configure your `.env` file

Copy the sample:

```bash
cp .env.sample .env
```

---
## Create an environment
python -m venv .venv (can use uv too)

---

## Install Dependencies (Local)

```bash
pip install -r requirements.txt
```

---

## Spin up postgres and couchdb instances from docker
```bash
docker compose up -d
```


---

## 🚀 Run the App

Choose your provider:

```bash
python main.py --provider anthropic
# or
python main.py --provider openai
```
