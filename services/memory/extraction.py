"""Memory extraction logic (rules-first, LLM fallback later)."""
import re
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class Candidate:
    """Memory candidate from extraction."""
    type: str
    text: str
    importance: float
    metadata: Dict[str, Any]


class RuleExtractor:
    """Rule-based memory extractor."""
    
    def __init__(self, rules_path: Optional[Path] = None):
        """Initialize extractor with rules.
        
        :param rules_path: Path to rules YAML file
        :type rules_path: Optional[Path]
        """
        if rules_path is None:
            rules_path = Path(__file__).parent / "extraction_rules.yaml"
        
        with open(rules_path) as f:
            config = yaml.safe_load(f)
        
        self.rules = config["rules"]
        self.reject_phrases = set(p.lower() for p in config["reject_phrases"])
        self.validation = config["validation"]
    
    def extract(self, messages: List[Dict[str, str]]) -> List[Candidate]:
        """Extract memory candidates from messages.
        
        :param messages: List of messages with role and content
        :type messages: List[Dict[str, str]]
        :return: List of memory candidates
        :rtype: List[Candidate]
        """
        candidates = []
        
        for msg in messages:
            if msg.get("role") != "user":
                continue
            
            content = msg.get("content", "").strip()
            if not content:
                continue
            
            for rule in self.rules:
                for pattern in rule["patterns"]:
                    for match in re.finditer(pattern, content, re.IGNORECASE):
                        text = self._format_text(rule["template"], match.groupdict())
                        
                        if self._validate_candidate(text, rule["type"]):
                            candidates.append(Candidate(
                                type=rule["type"],
                                text=text,
                                importance=rule["importance"],
                                metadata={"rule": rule["name"], "matched": match.group(0)},
                            ))
        
        return self._deduplicate(candidates)
    
    def _format_text(self, template: str, groups: Dict[str, str]) -> str:
        """Format template with matched groups.
        
        :param template: Template string
        :type template: str
        :param groups: Matched groups
        :type groups: Dict[str, str]
        :return: Formatted text
        :rtype: str
        """
        # Clean up captured groups
        cleaned = {}
        for key, value in groups.items():
            if value:
                value = value.strip()
                value = re.sub(r'\s+', ' ', value)
                cleaned[key] = value
        
        try:
            # Handle special case for likes/dislikes verb
            if "verb" in template and "verb" not in cleaned:
                if "like" in groups or "love" in groups:
                    cleaned["verb"] = groups.get("like") or groups.get("love")
                elif "hate" in groups or "dislike" in groups:
                    cleaned["verb"] = groups.get("hate") or groups.get("dislike")
            
            return template.format(**cleaned)
        except KeyError:
            return template
    
    def _validate_candidate(self, text: str, mem_type: str) -> bool:
        """Validate candidate against rules.
        
        :param text: Candidate text
        :type text: str
        :param mem_type: Memory type
        :type mem_type: str
        :return: True if valid
        :rtype: bool
        """
        text_lower = text.lower().strip()
        
        # Reject generic phrases
        if text_lower in self.reject_phrases:
            return False
        
        # Reject too long
        if len(text) > self.validation["max_text_length"]:
            return False
        
        # Check URL rules
        url_patterns = self.validation["url_patterns"]
        has_url = any(re.search(p, text, re.IGNORECASE) for p in url_patterns)
        
        if has_url and mem_type not in self.validation["allow_urls_for_types"]:
            return False
        
        return True
    
    def _deduplicate(self, candidates: List[Candidate]) -> List[Candidate]:
        """Deduplicate candidates by normalized text.
        
        :param candidates: List of candidates
        :type candidates: List[Candidate]
        :return: Deduplicated list
        :rtype: List[Candidate]
        """
        seen = {}
        for cand in candidates:
            key = (cand.type, cand.text.lower().strip())
            if key not in seen or cand.importance > seen[key].importance:
                seen[key] = cand
        
        return list(seen.values())
