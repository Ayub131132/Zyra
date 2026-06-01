import pytest
from zyra.lexer import Lexer
from zyra.parser import Parser
from zyra.compiler import Compiler

def test_compiler_basic():
    code = '''
    command "/start" {
        reply "Hello World"
    }
    '''
    tokens = Lexer(code).tokenize()
    parser = Parser(tokens)
    ast = parser.parse()
    compiler = Compiler()
    py_code = compiler.compile(ast)
    
    assert 'async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):' in py_code
    assert 'await update.message.reply_text(\'Hello World\')' in py_code
    assert 'CommandHandler(\'start\', start)' in py_code
    assert 'def main():' in py_code
