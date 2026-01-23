#include <iostream>
#include <stack>
using namespace std;
int main() {
    string infix;
    string postfix = "";
    stack<char> s;
    cout << "Enter infix expression: ";
    cin >> infix;
    for (int i = 0; i < infix.length(); i++) {
        char ch = infix[i];
        if (ch >= 'A' && ch <= 'Z') {
            postfix = postfix + ch;

        }
        else if (ch == '(') {
            s.push(ch);
        }
        else if (ch == ')') {
            while (s.top() != '(') {
                postfix = postfix + s.top();
                s.pop();
            }
            s.pop();
        }
        else {
            if (s.empty()) {
                s.push(ch);
            }
            else if (ch == '+' || ch == '-') {
                while (!s.empty() && s.top() != '(') {
                    postfix = postfix + s.top();
                    s.pop();
                }
                s.push(ch)
            }
            else if (ch == '*' || ch == '/') {
                while (!s.empty() &&
                      (s.top() == '*' || s.top() == '/')) {
                    postfix = postfix + s.top();
                    s.pop();
                }
                s.push(ch);
            }
        }
    }
    while (!s.empty()) {
        postfix = postfix + s.top();
        s.pop();
    }

    cout << "Postfix expression: " << postfix;
    return 0;
}