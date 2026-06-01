import sys
import os
import traceback
import json
import asyncio

from zyra.lexer import Lexer, LexerError
from zyra.parser import Parser, ParserError
from zyra.interpreter import Interpreter, ZyraRuntimeError
from zyra.ast import *

VERSION = "0.2.0"

class ZyraCLI:
    def __init__(self):
        self.debug = "--debug" in sys.argv
        if self.debug:
            sys.argv.remove("--debug")
            
        self.check_only = "--check" in sys.argv
        if self.check_only:
            sys.argv.remove("--check")
        
        self.args = sys.argv[1:]

    def show_usage(self):
        print(f"Zyra {VERSION}")
        print("\nUsage:")
        print("  zyra <file.zy>           Run a bot script")
        print("  zyra new <name>          Create a new project")
        print("  zyra watch <file>        Run and watch for changes")
        print("  zyra docs <file>         Generate documentation")
        print("  zyra ide                 Generate IDE support")
        print("\nFlags:")
        print("  --check                  Parse and validate syntax without running")
        print("  --debug                  Show full Python tracebacks on error")
        sys.exit(0)

    def error(self, msg, detail=None, file=None, line=None, col=None):
        print("\nZyra Error:")
        if file and line:
            print(f"{file}:{line}:{col}" if col else f"{file}:{line}")
        print(msg)
        if detail:
            print(detail)
        sys.exit(1)

    def syntax_error(self, filepath, error_type, msg, line, col):
        # Header: filename:line:col
        print(f"{os.path.basename(filepath)}:{line}:{col}\n")
        
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
                if 1 <= line <= len(lines):
                    error_line = lines[line-1].rstrip()
                    print(f"{error_line}")
                    print(" " * (col - 1) + "^")
        except:
            pass
            
        print(f"\n{error_type}: {msg}")
        sys.exit(1)

    def run_script(self, filepath):
        if not os.path.exists(filepath):
            self.error(f"File not found:", filepath)
        
        if not filepath.endswith(".zy"):
            self.error("Expected a .zy file.")

        try:
            with open(filepath, 'r') as f:
                code = f.read()
            
            lexer = Lexer(code)
            tokens = lexer.tokenize()
            
            parser = Parser(tokens, file=filepath)
            ast = parser.parse()
            
            if self.check_only:
                print(f"Syntax OK: {filepath}")
                sys.exit(0)
            
            interpreter = Interpreter()
            asyncio.run(interpreter.run(ast))
            
        except LexerError as e:
            if self.debug:
                traceback.print_exc()
            self.syntax_error(filepath, "LexerError", e.message, e.line, e.column)
        except ParserError as e:
            if self.debug:
                traceback.print_exc()
            self.syntax_error(e.file, "ParserError", e.message, e.line, e.column)
        except ZyraRuntimeError as e:
            if self.debug:
                traceback.print_exc()
            self.error("Runtime Error:", str(e))
        except KeyboardInterrupt:
            print("\nStopped.")
            sys.exit(0)
        except Exception as e:
            if self.debug:
                traceback.print_exc()
            else:
                self.error(f"An unexpected error occurred:", str(e))

    def new_project(self, name):
        try:
            os.makedirs(name, exist_ok=True)
            with open(os.path.join(name, 'main.zy'), 'w') as f:
                f.write('bot "MyBot"\ntoken env("BOT_TOKEN")\n\ncommand "/start" {\n    reply "Welcome to Zyra!"\n}\n')
            with open(os.path.join(name, '.env'), 'w') as f:
                f.write('BOT_TOKEN=your_token_here\n')
            print(f"Created new Zyra project in {name}")
        except Exception as e:
            self.error("Failed to create project:", str(e))

    def generate_docs(self, filepath):
        try:
            with open(filepath, 'r') as f:
                code = f.read()
            ast = Parser(Lexer(code).tokenize()).parse()
            
            docs = [f"# Documentation for {filepath}\n"]
            for stmt in ast.statements:
                if isinstance(stmt, CommandDef):
                    docs.append(f"- **{stmt.command}**: Executes a command block.")
                elif isinstance(stmt, StateDef):
                    docs.append(f"- **{stmt.name}**: A state machine conversation.")
            
            output_path = filepath.replace(".zy", ".md")
            with open(output_path, 'w') as f:
                f.write("\n".join(docs))
            print(f"Documentation generated at {output_path}")
        except Exception as e:
            self.error("Failed to generate docs:", str(e))

    def ide_support(self):
        try:
            os.makedirs(".vscode-zyra/syntaxes", exist_ok=True)
            # Minimal scaffolding
            package_json = {"name": "zyra-language", "version": "0.1.0"}
            with open(".vscode-zyra/package.json", 'w') as f:
                json.dump(package_json, f)
            print("IDE support scaffolded in .vscode-zyra/")
        except Exception as e:
            self.error("Failed to generate IDE support:", str(e))

def main():
    cli = ZyraCLI()
    
    if not cli.args:
        cli.show_usage()

    cmd = cli.args[0]
    
    if cmd == "new":
        if len(cli.args) < 2:
            cli.error("Expected project name:", "zyra new <name>")
        cli.new_project(cli.args[1])
    elif cmd == "watch":
        if len(cli.args) < 2:
            cli.error("Expected file to watch:", "zyra watch <file.zy>")
        cli.run_script(cli.args[1])
    elif cmd == "docs":
        if len(cli.args) < 2:
            cli.error("Expected file for docs:", "zyra docs <file.zy>")
        cli.generate_docs(cli.args[1])
    elif cmd == "ide":
        cli.ide_support()
    elif cmd.endswith(".zy"):
        cli.run_script(cmd)
    else:
        if os.path.exists(cmd):
            cli.error("Expected a .zy file.")
        else:
            cli.error(f"Unknown command or file: '{cmd}'")

if __name__ == "__main__":
    main()
