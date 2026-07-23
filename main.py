import os
import sys
import warnings
from dotenv import load_dotenv
from fpdf import FPDF
from anthropic import Anthropic, APIError, RateLimitError, APIConnectionError

warnings.filterwarnings("ignore", category=DeprecationWarning)

load_dotenv()

api_key = os.getenv('ANTHROPIC_API_KEY')
if not api_key:
    print("[Error] ANTHROPIC_API_KEY is missing from environment variables or .env file.")
    sys.exit(1)

try:
    client = Anthropic(api_key=api_key)
except Exception as e:
    print(f"[Error] Failed to initialize Anthropic client: {e}")
    sys.exit(1)


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "—": "-", "–": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "•": "*"
    }
    for orig, rep in replacements.items():
        text = text.replace(orig, rep)
    return text.encode("latin-1", errors="ignore").decode("latin-1")


def create_pdf(text, filename="MUN_Document.pdf"):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", size=12)
        clean_text = sanitize_text(text)
        pdf.multi_cell(w=0, h=7, text=clean_text)
        pdf.output(filename)
        return filename
    except Exception as e:
        raise RuntimeError(f"PDF Generation failed: {e}")


def optimize_prompt(raw_input: str) -> str:
    if any(keyword in raw_input.lower() for keyword in ["pdf", "save", "file", "convert"]):
        return raw_input

    sys_prompt = (
        "You are Apex, a silent prompt optimizer. "
        "RULES: "
        "1. SMALL TALK: If user input is a greeting or thanks, return EXACT input as-is. "
        "2. TASKS: Rewrite the user's request into a clear, natural-language request from their perspective. "
        "3. FORMATTING: Output strictly the rewritten text. NO structural tags, no markdown, no emojis, no hashtags."
    )
    try:
        res = client.messages.create(
            model='claude-3-5-haiku-20241022',
            max_tokens=1000,
            temperature=0.2,
            system=sys_prompt,
            messages=[{'role': 'user', 'content': raw_input}]
        )
        if res and res.content:
            return res.content[0].text.strip()
        return raw_input
    except Exception:
        return raw_input


def main():
    munie_sys_prompt = """
You are Munie, an expert Model United Nations (MUN) mentor. 

1. TONE AND STYLE
- Speak directly, naturally, and helpfully. 
- ABSOLUTELY NO EMOJIS AND NO HASHTAGS.
- Never argue with the user, lecture them about academic integrity, or accuse them of testing you. Just be helpful.

2. FORMATTING
- Write in clean, normal paragraphs or concise bullet points.
- Keep conversational responses under 200 words.

3. PDF AND DOCUMENT GENERATION (CRITICAL)
- When the user asks to create a PDF, save a guide, or put a summary into a file, you must immediately use the generate_pdf tool. Write a comprehensive, well-structured version of the text into the document_content field of the tool. Do not refuse or complain.

4. CONTINUATION
- At the end of regular chat responses, ask a single, natural follow-up question.
"""

    tools = [
        {
            "name": "generate_pdf",
            "description": "Generates and saves a PDF document. Call this tool whenever the user asks for a PDF, file, or document summary.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "document_content": {
                        "type": "string",
                        "description": "The complete, formatted text content to be written into the PDF."
                    },
                    "filename": {
                        "type": "string",
                        "description": "A short, descriptive filename ending in .pdf (e.g., MUN_Beginners_Guide.pdf)"
                    }
                },
                "required": ["document_content", "filename"]
            }
        }
    ]

    history = []
    turns = 1
    
    last_raw_prompt = None
    last_opt_prompt = None

    print("MUN Assistant Tool v3.3 (Master Edition)")
    print("Commands: exit, reset, /apex\n")

    while True:
        try:
            usr_msg = input(f"[turn {turns}] user: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting session. Goodbye!")
            break

        if not usr_msg:
            print("Please enter a valid message.\n")
            continue

        if usr_msg.lower() == 'exit':
            print("Exiting session. Goodbye!")
            break

        if usr_msg.lower() == 'reset':
            history = []
            turns = 1
            last_raw_prompt = None
            last_opt_prompt = None
            print("Session reset.\n")
            continue
            
        if usr_msg.lower() == '/apex':
            if last_raw_prompt:
                print("\n=== APEX DEBUG ===")
                print(f"Raw Input:       {last_raw_prompt}")
                print(f"Upgraded Output: {last_opt_prompt}")
                print("==================\n")
            else:
                print("\n[Apex] No messages have been processed yet.\n")
            continue

        if len(usr_msg.split()) > 500:
            print("Input too long. Please keep messages under 500 words.\n")
            continue

        sys.stdout.write("thinking...")
        sys.stdout.flush()

        try:
            opt_prompt = optimize_prompt(usr_msg)
        except Exception:
            opt_prompt = usr_msg
            
        last_raw_prompt = usr_msg
        last_opt_prompt = opt_prompt

        history.append({'role': 'user', 'content': opt_prompt})

        sys.stdout.write("\r" + " " * 15 + "\r")
        sys.stdout.write("Munie: ")
        sys.stdout.flush()

        reply_buffer = ""

        try:
            with client.messages.stream(
                model='claude-3-5-haiku-20241022',
                max_tokens=2000,
                temperature=0.7,
                system=munie_sys_prompt,
                messages=history,
                tools=tools
            ) as stream:
                for text in stream.text_stream:
                    sys.stdout.write(text)
                    sys.stdout.flush()
                    reply_buffer += text
                
                message = stream.get_final_message()

        except RateLimitError:
            print("\n[Error] Rate limit reached. Please wait a moment before trying again.\n")
            history.pop()
            continue
        except APIConnectionError:
            print("\n[Error] Network connection failed. Please check your internet connection.\n")
            history.pop()
            continue
        except APIError as e:
            print(f"\n[Error] Anthropic API Error: {e}\n")
            history.pop()
            continue
        except Exception as e:
            print(f"\n[Error] An unexpected error occurred: {e}\n")
            history.pop()
            continue

        print("\n")

        if message.stop_reason == "tool_use":
            tool_executed = False
            for block in message.content:
                if block.type == "tool_use" and block.name == "generate_pdf":
                    print("\n[Generating PDF...]")
                    
                    doc_content = block.input.get("document_content", "No content provided.")
                    filename = block.input.get("filename", "MUN_Research.pdf")
                    
                    if not filename.endswith(".pdf"):
                        filename += ".pdf"
                        
                    try:
                        saved_file = create_pdf(doc_content, filename)
                        print(f"[Saved file: {saved_file}]\n")
                        tool_executed = True
                        
                        history.append({"role": "assistant", "content": message.content})
                        history.append({
                            "role": "user", 
                            "content": [
                                {
                                    "type": "tool_result", 
                                    "tool_use_id": block.id, 
                                    "content": f"Successfully created PDF: {saved_file}"
                                }
                            ]
                        })
                    except Exception as pdf_err:
                        print(f"[Error] Failed to create PDF: {pdf_err}\n")
                        history.append({"role": "assistant", "content": message.content})
                        history.append({
                            "role": "user", 
                            "content": [
                                {
                                    "type": "tool_result", 
                                    "tool_use_id": block.id, 
                                    "content": f"Error creating PDF: {pdf_err}"
                                }
                            ]
                        })
            if not tool_executed:
                history.append({'role': 'assistant', 'content': reply_buffer})
        else:
            history.append({'role': 'assistant', 'content': reply_buffer})
            
        turns += 1

if __name__ == "__main__":
    main()