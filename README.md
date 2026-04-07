# 🧠 LC-RAG

LC-RAG is a **Retrieval-Augmented Generation (RAG) based chatbot system** that allows **admins** to create and manage chatbots, while **users** can interact with them seamlessly. It integrates **FastAPI**, **Firebase**, and **Pinecone** to deliver intelligent, scalable, and real-time conversational AI experiences.

---

## 🚀 Features

- **Admin Panel:** Create, configure, and manage chatbots.  
- **User Interaction:** Engage with chatbot instances in real-time.  
- **Firebase Integration:** Secure authentication, database, and storage.  
- **Pinecone Vector Search:** Efficient retrieval for RAG workflows.  
- **FastAPI Backend:** Lightweight, high-performance API for serving requests.

---

## 🛠️ Tech Stack

- **Backend Framework:** FastAPI  
- **Database & Auth:** Firebase  
- **Vector Store:** Pinecone  
- **Language:** Python 3.9+  

---

## ⚙️ Setup & Installation

### 1. Clone the Repository

```bash
git clone https://github.com/<your-username>/lc-rag.git
cd lc-rag
2. Create and Activate a Virtual Environment
bash
Copy code
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
3. Install Dependencies
bash
Copy code
pip install -r requirements.txt
🔐 Environment Configuration
You’ll need two key configuration files before running the project:

1. .env file
Create a .env file in the project root and add the following variables:

bash
Copy code
FIREBASE_APIKEY=your_firebase_api_key
FIREBASE_STORAGE_BUCKET=your_firebase_storage_bucket
ENCRYPTION_KEY=your_encryption_key
SMTP_SERVER=smtp.gmail.com
SMTP_PORT= server_port
SENDER_EMAIL=your_sender_email
SENDER_PASSWORD=your_sender_email_password
PINECONE_API_KEY=your_pinecone_api_key
OPENAI_API_KEY=your_openai_api_key

(Adjust keys as needed for your setup.)

2. firebase_config.json file
Download your Firebase service account key from the Firebase Console and save it as:

pgsql
Copy code
firebase_config.json
in the project root directory.

▶️ Running the Application
Start the FastAPI server with:

bash
Copy code
uvicorn main:app --reload
Then open your browser at:

cpp
Copy code
http://127.0.0.1:8000
🧩 Project Structure
bash
Copy code
lc-rag/
│
├── main.py # FastAPI entry point
├── requirements.txt # Python dependencies
├── .env # Environment variables
├── firebase_config.json # Firebase service config
│
├── config/ # Configuration files
├── routes/ # API route definitions
├── utils/
├── models/ # Pydantic data models
│
└── README.md
