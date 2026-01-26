# ==================== IMPORTS ====================
import os
import re
import traceback
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from functools import wraps
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Google Gemini (support both older google.generativeai and newer google.genai APIs)
GENAI_V2 = False
genai = None
GEMINI_SUPPORT = False

try:
    # Try legacy first (more stable)
    import google.generativeai as genai_old
    genai = genai_old
    GENAI_V2 = False
    GEMINI_SUPPORT = True
    logging.info("google.generativeai library loaded")
except Exception as e:
    try:
        from google import genai as genai_v2
        genai = genai_v2
        GENAI_V2 = True
        GEMINI_SUPPORT = True
        logging.info("google.genai library loaded")
    except Exception as e2:
        GEMINI_SUPPORT = False
        logging.warning(f"Google Gemini libraries not available: {e} / {e2}")

# ==================== ENV LOAD ====================
load_dotenv()
# ==================== CONFIG ====================
class Config:
    """Application configuration management"""

    # Flask configuration
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    ENV = os.getenv("FLASK_ENV", "development")

    # Upload configuration (kept but not required now)
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 50 * 1024 * 1024))
    ALLOWED_EXTENSIONS = {"pdf"}

    # API Keys
    # GEMINI_API_KEY must be set in the environment or in a local .env file.
    # Do NOT commit real API keys into source control.
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # API configuration
    API_TIMEOUT = int(os.getenv("API_TIMEOUT", 30))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))

    @classmethod
    def validate_config(cls) -> tuple[bool, List[str]]:
        warnings: List[str] = []

        if not cls.GEMINI_API_KEY:
            warnings.append("GEMINI_API_KEY not set - Gemini calls will fail")

        if cls.SECRET_KEY == "dev-secret-key-change-in-production":
            warnings.append("Using default SECRET_KEY - change in production!")

        if not GEMINI_SUPPORT:
            warnings.append("google-generativeai not installed - Gemini unavailable")

        return len(warnings) == 0, warnings


# ==================== GEMINI WRAPPER ====================
class GeminiChat:
    """
    Simple wrapper around Gemini for direct QA (no PDF).
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = None
        self.client = None
        self.model_id = "gemini-2.5-flash"

        if GEMINI_SUPPORT and self.api_key:
            try:
                if GENAI_V2:
                    # Newer google.genai client
                    try:
                        self.client = genai.Client(api_key=self.api_key)
                        logging.info("GenAI client initialised (v2)")
                    except Exception:
                        # Some SDK versions use genai.configure
                        genai.configure(api_key=self.api_key)
                        self.client = genai
                        logging.info("GenAI configured (v2) via configure")
                else:
                    # Older google.generativeai
                    genai.configure(api_key=self.api_key)
                    # keep compatibility with older wrapper usage
                    try:
                        self.model = genai.GenerativeModel("gemini-pro")
                    except Exception:
                        self.model = None
                    logging.info("Gemini model initialised (legacy)")
            except Exception as e:
                logging.error(f"Failed to configure Gemini: {e}")
                self.model = None
                self.client = None
        else:
            self.model = None
            self.client = None
            logging.warning("Gemini API not available or key missing")

    @staticmethod
    def mode_instruction(mode: str) -> str:
        """
        Map UI mode to answer style instructions per system rules.
        """
        mode = (mode or "").lower()
        if mode == "exam":
            return (
                "Format as concise bullet points. Focus on: definitions, key formulas, key steps, "
                "important conditions, and 1–2 short examples. Each bullet should be short and exam-ready. "
                "Use clear ASCII or LaTeX-like notation for math (e.g., F = m * a). Use Markdown for readability."
            )
        if mode == "cheatsheet":
            return (
                "Respond as a compact cheat sheet. Use tiny headings and short bullet points. "
                "Include only the most important formulas, facts, and quick tips. Avoid long explanations. "
                "Use ASCII or LaTeX notation for formulas (e.g., v = u + at)."
            )
        if mode == "descriptive":
            return (
                "Respond in well-structured paragraphs. Explain concepts clearly with intuition and simple examples. "
                "You may be longer, like a theory answer in an exam. Use Markdown headings and lists where helpful. "
                "Include formulas in clear ASCII or LaTeX notation (e.g., E = m * c^2)."
)
        return "Answer the question directly. Answer only about the user's question; do not invent extra context."
    def ask(self, query: str, mode: str = "exam") -> Dict[str, Any]:
        """
        Call Gemini with the given question and mode.
        """
        # Try to use the model if available
        if GEMINI_SUPPORT and getattr(self, "model", None) is not None:
            try:
                style = self.mode_instruction(mode)
                prompt = f"""You are a helpful study assistant.\n\nInstructions:\n{style}\n\nUser question:\n{query}"""

                response = self.model.generate_content(prompt)
                answer = getattr(response, "text", None) or str(response)
                logging.info("✅ Answer from Gemini Cloud")
                return {"answer": answer, "confidence": 0.9, "found_in_pdf": False, "pdf_name": None}
            except Exception as e:
                logging.error(f"Gemini generation error: {e}, falling back to local")

        # Fallback: local generator that tailors answers by mode
        logging.info("Using local fallback generator")
        qtext = (query or "").strip()
        # try to infer mode from query if not explicitly provided
        if not mode:
            ql = qtext.lower()
            if "cheat" in ql:
                mode = "cheatsheet"
            elif "describ" in ql or "detailed" in ql:
                mode = "descriptive"
            elif "exam" in ql or "bullet" in ql:
                mode = "exam"
            else:
                mode = "exam"

        def local_answer(question: str, mode_name: str) -> str:
            s = question.strip().lower()
            
            # ===== PHYSICS: NEWTON'S LAWS =====
            if "inertia" in s or ("law" in s and "first" in s and "newton" in s):
                if mode_name == "exam":
                    return (
                        "• **Definition**: An object remains at rest or in uniform motion (v = constant) unless a net external force acts on it.\n"
                        "• **Key**: Σ F = 0 ⇒ a = 0 (no acceleration).\n"
                        "• **Inertia**: Mass measures resistance to acceleration; higher mass ⇒ harder to accelerate.\n"
                        "• **Example**: A book on a smooth table stays still; a hockey puck slides at constant speed on ice."
                    )
                if mode_name == "cheatsheet":
                    return (
                        "**Newton's 1st Law (Inertia)**\n"
                        "- Σ F = 0 ⇒ v = constant or v = 0\n"
                        "- Inertia ∝ mass\n"
                        "- No friction → objects keep moving forever"
                    )
                return (
                    "Newton's first law (law of inertia) states that a body maintains its state of rest or uniform straight-line motion unless a net external force acts on it. Inertia is the intrinsic property of matter quantifying resistance to changes in motion; it is proportional to mass.\n\n"
                    "**Key idea**: If the sum of all forces is zero, the object neither accelerates nor decelerates. A book resting on a table experiences zero net force (gravity balanced by normal force) and stays at rest. A hockey puck on near-frictionless ice continues sliding at constant velocity because negligible friction acts on it. This law establishes the foundation for inertial reference frames."
                )
            
            if "third" in s and "newton" in s:
                if mode_name == "exam":
                    return (
                        "• **Statement**: For every action force, there is an equal and opposite reaction force.\n"
                        "• **Key**: Forces always occur in pairs; they act on *different* objects and do not cancel.\n"
                        "• **Notation**: If A exerts F_AB on B, then B exerts F_BA = -F_AB on A.\n"
                        "• **Example**: When you jump, your legs push down on ground; ground pushes up on you."
                    )
                if mode_name == "cheatsheet":
                    return (
                        "**Newton's 3rd Law**\n"
                        "- F_AB = -F_BA (equal magnitude, opposite direction)\n"
                        "- Forces act on different objects\n"
                        "- Examples: rocket exhaust ↔ thrust, swimmer ↔ water"
                    )
                return (
                    "Newton's third law states that forces always come in pairs: when object A exerts a force (action) on object B, then B simultaneously exerts a force (reaction) on A, equal in magnitude and opposite in direction. These action-reaction pairs act on *different* objects, so they do not cancel.\n\n"
                    "**Example**: When you jump, your legs push downward on the ground (action); the ground pushes upward on you (reaction) with equal force. The forces are equal and opposite but act on different bodies, allowing you to accelerate upward. A rocket expels exhaust downward; the exhaust exerts equal and opposite force on the rocket, producing thrust."
                )
            
            if "second" in s and "newton" in s or "f = m" in s and "a" in s:
                if mode_name == "exam":
                    return (
                        "• **Newton's 2nd Law**: F = m * a (force = mass × acceleration).\n"
                        "• **Key**: Greater force ⇒ greater acceleration (fixed mass); greater mass ⇒ less acceleration (fixed force).\n"
                        "• **Units**: 1 Newton (N) = 1 kg⋅m/s².\n"
                        "• **Example**: 2 kg block + 10 N force → a = 10/2 = 5 m/s²."
                    )
                if mode_name == "cheatsheet":
                    return (
                        "**Newton's 2nd Law**\n"
                        "- F = m * a\n"
                        "- 1 N = 1 kg⋅m/s²\n"
                        "- Σ F = m * a (net force)"
                    )
                return (
                    "Newton's second law: F = m * a. Force (Newtons) is any push or pull; mass (kg) is the amount of material; acceleration (m/s²) is the rate of change of velocity.\n\n"
                    "An object with larger mass requires more force for the same acceleration. For example, 10 N on a 1 kg ball produces 10 m/s² acceleration, while the same 10 N on a 2 kg ball produces only 5 m/s². Weight is gravitational force: W = m * g (where g ≈ 9.8 m/s² on Earth)."
                )
            
            # ===== MATH: QUADRATIC EQUATIONS =====
            if "quadratic" in s or "ax" in s and "bx" in s:
                if mode_name == "exam":
                    return (
                        "• **Form**: a*x² + b*x + c = 0 (where a ≠ 0).\n"
                        "• **Quadratic formula**: x = (-b ± √(b² - 4*a*c)) / (2*a).\n"
                        "• **Discriminant**: Δ = b² - 4*a*c. If Δ > 0 → 2 real roots; Δ = 0 → 1 real root; Δ < 0 → no real roots.\n"
                        "• **Example**: x² - 5*x + 6 = 0 has roots x = 2 and x = 3."
                    )
                if mode_name == "cheatsheet":
                    return (
                        "**Quadratic Formula**\n"
                        "- x = (-b ± √(b² - 4ac)) / 2a\n"
                        "- Δ = b² - 4ac (discriminant)\n"
                        "- Δ > 0: two roots; Δ = 0: one root; Δ < 0: no real roots"
                    )
                return (
                    "A quadratic equation: a*x² + b*x + c = 0 (a ≠ 0). Solutions: x = (-b ± √(b² - 4*a*c)) / (2*a).\n\n"
                    "The discriminant Δ = b² - 4*a*c determines the roots: Δ > 0 gives two distinct real roots; Δ = 0 gives one repeated real root; Δ < 0 gives no real roots (two complex conjugates). For x² - 5*x + 6 = 0: a=1, b=-5, c=6, so Δ = 25-24 = 1. Roots: x = (5±1)/2, giving x = 3 and x = 2."
                )
            
            # ===== CS: COMPLEXITY & ALGORITHMS =====
            if "complexity" in s or "algorithm" in s or ("time" in s and "space" in s):
                if mode_name == "exam":
                    return (
                        "• **Time complexity**: How runtime grows with input size n (Big-O notation).\n"
                        "• **Common**: O(1) constant, O(log n) logarithmic, O(n) linear, O(n log n), O(n²) quadratic, O(2ⁿ) exponential.\n"
                        "• **Space complexity**: Extra memory used (excluding input).\n"
                        "• **Example**: Linear search O(n); binary search O(log n); merge sort O(n log n); bubble sort O(n²)."
                    )
                if mode_name == "cheatsheet":
                    return (
                        "**Big-O Complexity**\n"
                        "- O(1): constant | O(log n): binary search | O(n): linear\n"
                        "- O(n log n): merge sort | O(n²): bubble sort | O(2ⁿ): brute force\n"
                        "- Worst-case analysis"
                    )
                return (
                    "Time complexity (Big-O notation) describes how algorithm runtime grows with input size n. From fastest to slowest: O(1) constant, O(log n) logarithmic, O(n) linear, O(n log n), O(n²) quadratic, O(2ⁿ) exponential.\n\n"
                    "Space complexity measures extra memory beyond input. Linear search checks each element (O(n) time); binary search halves the search space each step (O(log n)). Merge sort (O(n log n)) is better than bubble sort (O(n²)) for large datasets. Analysis typically focuses on worst-case to guarantee performance."
                )
            
            # ===== GENERIC FALLBACK =====
            if mode_name == "exam":
                return (
                    "• Unable to provide a specific answer without more context.\n"
                    "• Please rephrase your question or specify a topic (physics, math, CS, etc.).\n"
                    "• Example: 'What is Newton's first law?' or 'How does binary search work?'"
                )
            if mode_name == "cheatsheet":
                return "**Unable to answer** — Please clarify with more detail or topic keywords."
            return "I don't have a specific answer yet. Please provide more context or choose from physics, mathematics, or computer science."

        answer_text = local_answer(qtext, mode)
        return {"answer": answer_text, "confidence": 0.6, "found_in_pdf": False, "pdf_name": None}


# ==================== WEB SEARCH & SCRAPING ====================
class WebSearch:
    """
    Web search and scraping utility for fetching answers from the internet.
    Uses DuckDuckGo search (free, no API key required) and web scraping.
    """

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        self.timeout = 10

    def search_duckduckgo(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """
        Search using DuckDuckGo (free, no API key needed).
        Returns list of dicts with 'title', 'url', 'snippet'.
        """
        try:
            url = f"https://duckduckgo.com/html/?q={quote(query)}"
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")
            results = []

            # Parse DuckDuckGo HTML results
            for item in soup.find_all("div", class_="result"):
                try:
                    title_elem = item.find("a", class_="result__url")
                    snippet_elem = item.find("a", class_="result__snippet")

                    if title_elem and snippet_elem:
                        title = title_elem.get_text(strip=True)
                        url_link = title_elem.get("href", "")
                        snippet = snippet_elem.get_text(strip=True)

                        results.append({
                            "title": title,
                            "url": url_link,
                            "snippet": snippet
                        })

                        if len(results) >= num_results:
                            break
                except Exception as e:
                    logging.warning(f"Error parsing search result: {e}")
                    continue

            return results
        except Exception as e:
            logging.error(f"DuckDuckGo search error: {e}")
            return []

    def scrape_content(self, url: str, max_length: int = 2000) -> str:
        """
        Scrape main content from a URL.
        Returns extracted text (limited length).
        """
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            # Get text
            text = soup.get_text(separator=" ", strip=True)
            # Clean up whitespace
            text = re.sub(r"\s+", " ", text)

            return text[:max_length]
        except Exception as e:
            logging.warning(f"Error scraping {url}: {e}")
            return ""

    def search_and_answer(self, query: str, mode: str = "exam") -> Dict[str, Any]:
        """
        Search the web for an answer and compile results.
        """
        try:
            logging.info(f"🔍 Searching web for: {query}")
            results = self.search_duckduckgo(query, num_results=3)

            if not results:
                logging.warning("No web results found")
                return {
                    "answer": "No web results found for your query. Please try a different search term.",
                    "confidence": 0.3,
                    "source": "web_search",
                    "results": []
                }

            # Compile answer from search results
            answer_parts = [f"**Web Search Results for:** {query}\n\n"]

            for i, result in enumerate(results, 1):
                title = result.get("title", "")
                snippet = result.get("snippet", "")
                url = result.get("url", "")

                if mode == "cheatsheet":
                    answer_parts.append(f"{i}. **{title}**\n   {snippet[:150]}...\n")
                else:
                    answer_parts.append(f"**{i}. {title}**\n{snippet}\n")

                if url:
                    answer_parts.append(f"   [Read more]({url})\n")

            answer_text = "\n".join(answer_parts)

            logging.info("✅ Answer compiled from web search")
            return {
                "answer": answer_text,
                "confidence": 0.7,
                "source": "web_search",
                "results": results
            }
        except Exception as e:
            logging.error(f"Web search failed: {e}")
            return {
                "answer": f"Web search failed: {str(e)}",
                "confidence": 0.2,
                "source": "web_search",
                "results": []
            }


# ==================== HYBRID ANSWER ENGINE ====================
class HybridAnswerEngine:
    """
    Combines Gemini AI, Web Search, and Local Fallback.
    Tries Gemini first, falls back to web search, then local answers.
    """

    def __init__(self, gemini_chat: "GeminiChat"):
        self.gemini_chat = gemini_chat
        self.web_search = WebSearch()

    def get_answer(self, query: str, mode: str = "exam", source: str = "auto") -> Dict[str, Any]:
        """
        Get answer from specified source or auto-select best available.
        source: 'auto' | 'gemini' | 'web' | 'local'
        """
        if source == "auto":
            # Try Gemini first if available
            if GEMINI_SUPPORT and getattr(self.gemini_chat, "model", None) is not None:
                return self.gemini_chat.ask(query, mode)
            # Fall back to web search
            else:
                return self.web_search.search_and_answer(query, mode)

        elif source == "gemini":
            return self.gemini_chat.ask(query, mode)

        elif source == "web":
            return self.web_search.search_and_answer(query, mode)

        elif source == "local":
            return self.gemini_chat.ask(query, mode)  # Uses fallback

        else:
            return {
                "answer": "Invalid source. Use 'auto', 'gemini', 'web', or 'local'.",
                "confidence": 0.0,
                "source": source
            }



app = Flask(__name__, template_folder="templates")
app.config.from_object(Config)

ok, cfg_warnings = Config.validate_config()
if not ok:
    for w in cfg_warnings:
        print("CONFIG WARNING:", w)

# Simple logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Initialize services
gemini_chat = GeminiChat(Config.GEMINI_API_KEY)
hybrid_engine = HybridAnswerEngine(gemini_chat)
web_search = WebSearch()


# ==================== ROUTES ====================
@app.route("/")
def home():
    """
    Render main UI (index.html).
    """
    return render_template("index.html")


@app.route("/ask", methods=["POST"])
def ask_question():
    """
    Direct QA via Gemini, Web Search, or Hybrid (auto-select).
    Expects JSON: { "query": "...", "mode": "exam" | "cheatsheet" | "descriptive", "source": "auto" | "gemini" | "web" | "local" }
    """
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    mode = data.get("mode", "exam")
    source = data.get("source", "auto")  # Default to auto-select

    if not query:
        return jsonify({"error": "No query provided"}), 400

    result = hybrid_engine.get_answer(query, mode=mode, source=source)
    return jsonify(result)


@app.route("/search", methods=["POST"])
def web_search_endpoint():
    """
    Direct web search endpoint.
    Expects JSON: { "query": "...", "mode": "exam" | "cheatsheet" | "descriptive" }
    """
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    mode = data.get("mode", "exam")

    if not query:
        return jsonify({"error": "No query provided"}), 400

    result = web_search.search_and_answer(query, mode=mode)
    return jsonify(result)


# (Optional) keep /upload stub if your frontend still calls it, but it will do nothing.
@app.route("/upload", methods=["POST"])
def upload_stub():
    """
    Optional: stub endpoint so existing frontend 'Upload PDF' button does not break.
    This no longer affects answers.
    """
    return jsonify(
        {
            "status": "success",
            "message": "PDF upload ignored (app now answers directly from Gemini).",
            "pages": 0,
            "chunks": 0,
            "text_length": 0,
        }
    )


# ==================== ENTRYPOINT ====================
if __name__ == "__main__":
    print("✅ Server starting on http://localhost:5000")
    app.run(debug=True, port=5000)
