import pytest
from zyra.lexer import Lexer
from zyra.parser import Parser
from zyra.ast import BotDef, CommandDef, ReplyStmt

def test_parser_bot():
    code = 'bot "MyBot"'
    tokens = Lexer(code).tokenize()
    parser = Parser(tokens)
    ast = parser.parse()
    
    assert len(ast.statements) == 1
    assert isinstance(ast.statements[0], BotDef)
    assert ast.statements[0].name == 'MyBot'

def test_parser_command():
    code = 'command "/start" { reply "Hello" }'
    tokens = Lexer(code).tokenize()
    parser = Parser(tokens)
    ast = parser.parse()
    
    assert len(ast.statements) == 1
    assert isinstance(ast.statements[0], CommandDef)
    assert ast.statements[0].command == '/start'
    assert len(ast.statements[0].body) == 1
    assert isinstance(ast.statements[0].body[0], ReplyStmt)
    assert ast.statements[0].body[0].text == 'Hello'
