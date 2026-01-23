#include <iostream>
#include <stack>
using namespace std;

int main() {
    string exp;
    cout << "Enter prefix expression (example: +23): ";
    cin >> exp;

    stack<int> s;

    for (int i = exp.length() - 1; i >= 0; i--) {
        char ch = exp[i];

        if (ch >= '0' && ch <= '9') {
            s.push(ch - '0');
        }
        else {
            int a = s.top(); s.pop();
            int b = s.top(); s.pop();

            if (ch == '+') s.push(a + b);
            if (ch == '-') s.push(a - b);
            if (ch == '*') s.push(a * b);
            if (ch == '/') s.push(a / b);
        }
    }

    cout << "Result = " << s.top();
    return 0;
}
