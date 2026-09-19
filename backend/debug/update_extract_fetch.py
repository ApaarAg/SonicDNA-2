import json
import re

def extract():
    log_path = 'C:/Users/apaar/.gemini/antigravity-ide/brain/22827745-5534-4cde-97df-076161ca9118/.system_generated/logs/transcript.jsonl'
    with open(log_path, encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            if data.get('step_index') == 444:
                content = data.get('content', '')
                print(f"Content length: {len(content)}")
                # Search for all strings starting with (() => and containing window.fetch = async
                pos = 0
                while True:
                    idx = content.find('window.fetch = async', pos)
                    if idx == -1:
                        break
                    print(f"Found 'window.fetch = async' at index {idx}")
                    # Find surrounding JavaScript block
                    start = content.rfind('(() =>', 0, idx)
                    end = content.find('})()', idx)
                    if start != -1 and end != -1:
                        js = content[start:end+4]
                        # Unescape double backslashes and quotes
                        js = js.replace('\\\\', '\\').replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                        print("FOUND MOCK SCRIPT LENGTH:", len(js))
                        with open('C:/Users/apaar/.gemini/antigravity-ide/brain/22827745-5534-4cde-97df-076161ca9118/scratch/extracted_mock_fetch.js', 'w', encoding='utf-8') as out:
                            out.write(js)
                        print("Saved to scratch/extracted_mock_fetch.js")
                        return
                    pos = idx + 1

if __name__ == '__main__':
    extract()
