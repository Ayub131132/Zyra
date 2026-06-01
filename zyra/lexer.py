import re
from typing import NamedTuple, List, Optional

class Token(NamedTuple):
    type: str
    value: str
    line: int
    column: int

class LexerError(Exception):
    def __init__(self, message, line, column):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column

    def __str__(self):
        return f"LexerError at line {self.line}, col {self.column}: {self.message}"

class Lexer:
    # Token specification
    # Note: MULTILINE_STRING must come before STRING
    token_specification = [
        ('COMMENT',          r'//.*'),                  # Single-line comment
        ('MULTILINE_STRING', r'"""[\s\S]*?"""'),        # Triple-quoted string
        ('STRING',           r'"[^"\n]*"'),             # Single-line string literal
        ('ARROW',            r'->|=>'),                 # Arrow operator
        ('EQUALS',           r'==?'),                   # Equals or strict equals
        ('OPERATOR',         r'[!><=+\-\*/]+'),          # Operators (+, -, *, /, >=, etc)
        ('LBRACE',           r'\{'),                    # Left brace
        ('RBRACE',           r'\}'),                    # Right brace
        ('LPAREN',           r'\('),                    # Left paren
        ('RPAREN',           r'\)'),                    # Right paren
        ('LBRACKET',         r'\['),                    # Left bracket
        ('RBRACKET',         r'\]'),                    # Right bracket
        ('DOT',              r'\.'),                    # Dot operator
        ('COMMA',            r','),                     # Comma
        ('ID',               r'[A-Za-z_][A-Za-z0-9_]*'), # Identifiers
        ('NUMBER',           r'\d+(\.\d*)?'),           # Integer or decimal number
        ('WS',               r'[ \t]+'),                # Whitespace
        ('NEWLINE',          r'\n'),                    # Line endings
        ('MISMATCH',         r'.'),                     # Any other character
    ]

    keywords = {
        'bot', 'token', 'env', 'command', 'message', 'contains',
        'reply', 'if', 'elif', 'else', 'and', 'or', 'not', 'button', 'callback',
        'state', 'ask', 'save', 'table', 'integer', 'text', 'primary',
        'insert', 'find', 'where', 'every', 'send', 'import', 'plugin',
        'ai', 'provider', 'model', 'ai_reply', 'admin', 'as', 'fn', 'return',
        'for', 'in', 'while', 'on', 'from', 'export', 'null'
    }

    @classmethod
    def keywords_upper(cls):
        return {k.upper() for k in cls.keywords}

    def __init__(self, code: str):
        self.code = code

    def tokenize(self) -> List[Token]:
        tokens = []
        tok_regex = '|'.join('(?P<%s>%s)' % pair for pair in self.token_specification)
        line_num = 1
        line_start = 0
        for mo in re.finditer(tok_regex, self.code):
            kind = mo.lastgroup
            value = mo.group(kind)
            column = mo.start() - line_start + 1
            
            if kind == 'NEWLINE':
                line_start = mo.end()
                line_num += 1
                continue
            elif kind == 'WS' or kind == 'COMMENT':
                continue
            elif kind == 'ID' and value in self.keywords:
                kind = value.upper()
            elif kind == 'MULTILINE_STRING':
                # Preserve exact text between triple quotes
                content = value[3:-3]
                # Important: Update line tracking for internal newlines
                newlines = value.count('\n')
                token = Token('STRING', content, line_num, column)
                if newlines > 0:
                    line_num += newlines
                    line_start = mo.start() + value.rfind('\n') + 1
                tokens.append(token)
                continue
            elif kind == 'STRING':
                value = value[1:-1] # Remove quotes
            elif kind == 'MISMATCH':
                raise LexerError(f"Unexpected character {value!r}", line_num, column)
            
            tokens.append(Token(kind, value, line_num, column))
            
        tokens.append(Token('EOF', '', line_num, 1))
        return tokens
