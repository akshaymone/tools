import re
import xml.sax.saxutils as saxutils

content = """
<p:notes>
    <a:p>
        <a:r><a:t>CATIA </a:t></a:r>
        <a:r><a:t>네이티브 모델</a:t></a:r>
        <a:r><a:t>을 </a:t></a:r>
    </a:p>
    <a:p>
        <a:r><a:t>English only</a:t></a:r>
    </a:p>
    <a:p><a:r><a:t>테스트</a:t></a:r></a:p>
</p:notes>
"""

_HANGUL_RE = re.compile(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]')

# Pass 1: Extract texts
texts_to_translate = []
matches = list(re.finditer(r'(<a:p(?:>|\s[^>]*>))(.*?)(</a:p>)', content, flags=re.DOTALL))
for match in matches:
    inner_xml = match.group(2)
    t_matches = re.finditer(r'(<a:t(?:>|\s[^>]*>))(.*?)(</a:t>)', inner_xml, flags=re.DOTALL)
    full_text = "".join(saxutils.unescape(t.group(2)) for t in t_matches)
    if _HANGUL_RE.search(full_text):
        texts_to_translate.append(full_text)

print("Texts to translate:", texts_to_translate)

# Mock translated texts
translated_texts = ["CATIA Native Model", "Test"]

# Pass 2: Replace
translated_iter = iter(translated_texts)

def para_replacer(para_match):
    prefix_p, inner_xml, suffix_p = para_match.group(1), para_match.group(2), para_match.group(3)
    
    t_matches = list(re.finditer(r'(<a:t(?:>|\s[^>]*>))(.*?)(</a:t>)', inner_xml, flags=re.DOTALL))
    full_text = "".join(saxutils.unescape(t.group(2)) for t in t_matches)
    
    if _HANGUL_RE.search(full_text):
        trans_text = next(translated_iter)
        first = True
        def t_replacer(t_match):
            nonlocal first
            prefix_t, _, suffix_t = t_match.group(1), t_match.group(2), t_match.group(3)
            if first:
                first = False
                return f"{prefix_t}{saxutils.escape(trans_text)}{suffix_t}"
            return f"{prefix_t}{suffix_t}"
            
        new_inner = re.sub(r'(<a:t(?:>|\s[^>]*>))(.*?)(</a:t>)', t_replacer, inner_xml, flags=re.DOTALL)
        return f"{prefix_p}{new_inner}{suffix_p}"
        
    return para_match.group(0)

new_content = re.sub(r'(<a:p(?:>|\s[^>]*>))(.*?)(</a:p>)', para_replacer, content, flags=re.DOTALL)
print("New Content:")
print(new_content)
