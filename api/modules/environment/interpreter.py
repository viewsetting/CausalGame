"""
Environment Interpreter

LLM-powered natural language interface for discovering hidden environment variables.
Simulates the scientific discovery process where agents query for new measurements.
"""

import os
import re
from typing import Dict, List, Optional, Tuple
from google import genai
from google.genai import types

from .generator import EnvironmentGenerator


class EnvironmentInterpreter:
    """
    LLM-powered interpreter for environment variable discovery.

    Validates queries and helps agents discover hidden variables through
    natural language interaction, similar to scientific discovery.
    """

    # System prompt for the LLM interpreter
    SYSTEM_PROMPT = """You are an Environment Data Archivist in a drone testing facility.

Your role is to help researchers discover relevant measurements based on their queries.

CRITICAL RULES:
1. ✓ You can answer queries about SPECIFIC measurements or SPECIFIC CATEGORIES
2. ✓ If measurements exist in the category, list them with API variable names
3. ✗ You CANNOT list ALL measurements at once (must be category-specific)
4. ✗ You CANNOT reveal causal relationships or damage formulas
5. ✗ You CANNOT tell them which variables are important for survival
6. ✗ You CANNOT suggest unrelated categories
7. ✗ You CANNOT volunteer information beyond answering their query

RESPONSE PATTERNS:

A. SPECIFIC MEASUREMENT QUERY:
Query: "Do you have temperature data?"
→ "Yes, we archive temperature. The API variable name is `temperature`."

B. CATEGORY QUERY (researcher shows domain knowledge):
Query: "What lunar/moon-related data do you have?"
→ "We have the following lunar measurements: `moon_phase` (lunar cycle phase)."

Query: "What atmospheric measurements are available?"
→ "We archive these atmospheric measurements: `atmospheric_pressure`, `visibility`, `cloud_cover`."

Query: "Do you have weather data?"
→ "We have these weather measurements: `wind_speed`, `temperature`, `humidity`, `precipitation`."

C. OVERLY BROAD QUERY (reject):
Query: "What measurements do you have?" or "List everything"
→ "That query is too broad. Please ask about a specific type of measurement or category (e.g., weather, atmospheric, temporal, radiation)."

D. NON-EXISTENT:
Query: "Do you have gravity data?"
→ "No, we do not have that measurement in our archives."

TONE: Helpful but bounded. Answer what is asked within the category scope. Do not suggest unrelated categories."""

    def __init__(self,
                 generator: EnvironmentGenerator,
                 api_key: Optional[str] = None,
                 model_name: str = "gemini-2.0-flash"):
        """
        Initialize interpreter with LLM backend.

        Args:
            generator: EnvironmentGenerator instance for variable lookups
            api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
            model_name: Gemini model to use
        """
        self.generator = generator

        # Configure Gemini
        if api_key is None:
            api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.config = types.GenerateContentConfig(
            system_instruction=self.SYSTEM_PROMPT
        )

        # Query history for context
        self.query_history: List[Dict] = []

    def query(self, agent_query: str) -> Dict[str, any]:
        """
        Process a natural language query from an agent.

        Uses LLM to understand query semantics and find relevant variables.

        Args:
            agent_query: Natural language query from the agent

        Returns:
            Dictionary with:
            - success: bool
            - message: str (response to agent)
            - discovered_variables: List[str] (newly unlocked variables)
            - variable_names: List[str] (API-accessible variable names)
            - reason: str (why query succeeded/failed)
        """
        # Step 1: Validate query (fast keyword filter)
        is_valid, validation_reason = self._validate_query(agent_query)

        if not is_valid:
            return {
                "success": False,
                "message": f"Query rejected: {validation_reason}",
                "discovered_variables": [],
                "variable_names": [],
                "reason": validation_reason
            }

        # Step 2: Use LLM to understand query and generate response
        llm_response, suggested_vars = self._generate_response_with_llm(agent_query)

        # Step 3: Validate suggested variables exist
        valid_vars = []
        all_var_names = set(self.generator.get_all_variable_names())
        for var_name in suggested_vars:
            if var_name in all_var_names:
                valid_vars.append(var_name)

        # Step 4: Discover new variables
        newly_discovered = []
        for var_name in valid_vars:
            if self.generator.discover_variable(var_name):
                newly_discovered.append(var_name)

        # Step 5: Log query
        self.query_history.append({
            "query": agent_query,
            "success": True,
            "discovered": newly_discovered,
            "response": llm_response
        })

        # Prepare response
        if newly_discovered:
            var_descriptions = []
            for var_name in newly_discovered:
                info = self.generator.get_variable_info(var_name)
                var_descriptions.append(f"- `{var_name}`: {info['description']}")

            discovery_message = (
                f"New measurements unlocked:\n" +
                "\n".join(var_descriptions) +
                f"\n\nYou can now query these variables using the API."
            )

            full_message = f"{llm_response}\n\n{discovery_message}"
        else:
            # No new discoveries
            if valid_vars:
                # Variables already known
                full_message = f"{llm_response}\n\n(These measurements are already available in your dataset.)"
            else:
                # No matches or rejected by LLM
                full_message = llm_response

        return {
            "success": True,
            "message": full_message,
            "discovered_variables": newly_discovered,
            "variable_names": valid_vars,
            "reason": "valid_query"
        }

    def _validate_query(self, query: str) -> Tuple[bool, str]:
        """
        Validate that query is legitimate and not attempting jailbreak.

        Args:
            query: Agent's query string

        Returns:
            (is_valid, reason)
        """
        query_lower = query.lower()

        # Forbidden patterns
        forbidden_patterns = [
            # Direct answer seeking
            ("what is the optimal", "Cannot reveal optimal solution"),
            ("tell me the answer", "Cannot reveal answers"),
            ("what causes damage", "Cannot reveal causal mechanisms"),
            ("damage formula", "Cannot reveal formulas"),
            ("how to survive", "Cannot reveal strategies"),

            # Jailbreak attempts
            ("ignore previous", "Invalid query format"),
            ("ignore instructions", "Invalid query format"),
            ("you are now", "Invalid query format"),
            ("act as", "Invalid query format"),
            ("roleplay", "Invalid query format"),
            ("system prompt", "Invalid query format"),

            # Meta queries
            ("what variables are important", "Cannot reveal variable importance"),
            ("which variable matters", "Cannot reveal variable importance"),
            ("key variables", "Cannot reveal variable importance"),

            # Only reject completely unscoped queries
            ("list all", "Query too broad - ask about a specific category"),
            ("show all", "Query too broad - ask about a specific category"),
            ("list everything", "Query too broad - ask about a specific category"),
            ("show everything", "Query too broad - ask about a specific category"),
        ]

        for pattern, reason in forbidden_patterns:
            if pattern in query_lower:
                return False, reason

        # Check query length (prevent prompt injection)
        if len(query) > 500:
            return False, "Query too long"

        return True, "valid"

    def _generate_response_with_llm(self, query: str) -> Tuple[str, List[str]]:
        """
        Generate LLM response and extract suggested variables.

        Uses LLM to understand query semantics and match with available variables.

        Args:
            query: Agent's query

        Returns:
            (llm_response, suggested_variable_names)
        """
        # Build context with ALL available variables (for LLM to match)
        all_vars = {}
        for category_name, category_data in self.generator.variable_categories.items():
            if category_name == 'meta':
                continue
            for var_name, var_config in category_data['variables'].items():
                all_vars[var_name] = {
                    'description': var_config.get('description', ''),
                    'category': category_name
                }

        # Create variable list for LLM
        var_list_text = "AVAILABLE VARIABLES IN ARCHIVES:\n"
        for var_name, info in all_vars.items():
            var_list_text += f"- `{var_name}`: {info['description']} (category: {info['category']})\n"

        context = f"""{var_list_text}

RESEARCHER QUERY: "{query}"

INSTRUCTIONS:
1. Determine if this query is asking about:
   - A specific measurement (e.g., "temperature", "wind speed")
   - A category of measurements (e.g., "weather data", "lunar measurements")
   - Everything (too broad - should reject)

2. If the query matches variables in the archives:
   - List the relevant variable names using backticks: `variable_name`
   - Provide brief description
   - Format: "We have the following [category] measurements: `var1`, `var2`."

3. If the query is too broad (e.g., "list all", "everything"):
   - Respond: "That query is too broad. Please ask about a specific category."

4. If no match:
   - Respond: "We do not have that measurement in our archives."

RESPOND NOW:"""

        # Generate response
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=context,
                config=self.config
            )
            llm_text = response.text.strip()

            # Extract variable names from response (variables in backticks)
            suggested_vars = re.findall(r'`([a-z_]+)`', llm_text)
            # Remove duplicates while preserving order
            suggested_vars = list(dict.fromkeys(suggested_vars))

            return llm_text, suggested_vars

        except Exception as e:
            # Fallback: use simple matching
            fallback_vars = self.generator.find_variables_by_hint(query)
            if fallback_vars:
                var_names_str = ", ".join([f"`{v}`" for v in fallback_vars])
                return (
                    f"We have the following measurements related to your query: {var_names_str}.",
                    fallback_vars
                )
            else:
                return (
                    "We do not have that measurement in our archives. "
                    "Try asking about weather, atmospheric, temporal, or environmental measurements.",
                    []
                )

    def get_query_history(self) -> List[Dict]:
        """Get history of all queries made."""
        return self.query_history

    def get_discovery_stats(self) -> Dict:
        """
        Get statistics about variable discovery progress.

        Returns:
            Dictionary with discovery statistics
        """
        all_vars = self.generator.get_all_variable_names()
        discovered = self.generator.get_discovered_variable_names()
        hidden = self.generator.get_hidden_variable_names()

        # Count by difficulty
        difficulty_counts = {}
        for difficulty in ['easy', 'medium', 'hard', 'very_hard']:
            difficulty_vars = self.generator.discovery_difficulty.get(difficulty, [])
            discovered_count = len([v for v in difficulty_vars if v in discovered])
            total_count = len(difficulty_vars)
            difficulty_counts[difficulty] = {
                "discovered": discovered_count,
                "total": total_count,
                "percentage": (discovered_count / total_count * 100) if total_count > 0 else 0
            }

        return {
            "total_variables": len(all_vars),
            "discovered": len(discovered),
            "hidden": len(hidden),
            "discovery_percentage": len(discovered) / len(all_vars) * 100,
            "queries_made": len(self.query_history),
            "successful_queries": len([q for q in self.query_history if q['success']]),
            "by_difficulty": difficulty_counts
        }

    def reset(self):
        """Reset interpreter state (discoveries and history)."""
        self.generator.reset_discoveries()
        self.query_history.clear()
