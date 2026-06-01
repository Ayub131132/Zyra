import pytest
from zyra.lexer import Lexer, Token

def test_lexer_basic():
    code = 'bot "TestBot"'
    lexer = Lexer(code)
    tokens = lexer.tokenize()
    assert len(tokens) == 3
    assert tokens[0].type == 'BOT'
    assert tokens[1].type == 'STRING'
    assert tokens[1].value == 'TestBot'
    assert tokens[2].type == 'EOF'

def test_lexer_symbols():
    code = 'command "/start" { reply "Hello" }'
    lexer = Lexer(code)
    tokens = lexer.tokenize()
    types = [t.type for t in tokens]
    assert types == ['COMMAND', 'STRING', 'LBRACE', 'REPLY', 'STRING', 'RBRACE', 'EOF']

def test_lexer_complex():
    code = '''
    let count = 0
    if count > 5 {
        reply "Premium"
    }
    '''
    lexer = Lexer(code)
    tokens = lexer.tokenize()
    types = [t.type for t in tokens]
    assert 'LET' in types
    assert 'ID' in types
    assert 'EQUALS' in types
    assert 'NUMBER' in types
    assert 'IF' in types
    assert 'OPERATOR' in types
