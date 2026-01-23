#include <iostream>
using namespace std;

class Stack {
private:
    int size;           // Maximum stack size
    int* array;         // Dynamic array for stack elements
    int top;            // Index of top element (-1 = empty)

public:
    // Constructor to initialize stack
    Stack(int s) {
        size = s;
        array = new int[size];  // Create array of given size
        top = -1;               // Stack starts empty
    }
    
    // Destructor to free memory
    ~Stack() {
        delete[] array;
    }
    
    // Check if stack is empty
    bool isEmpty() {
        return top == -1;
    }
    
    // Check if stack is full
    bool isFull() {
        return top == size - 1;
    }
    
    // Push (add) element to top
    void push(int item) {
        if (isFull()) {
            cout << "Stack Overflow! Cannot push." << endl;
            return;
        }
        top++;              // Move top pointer up
        array[top] = item;  // Add item at top
        cout << "Pushed " << item << endl;
    }
    
    // Pop (remove) top element
    int pop() {
        if (isEmpty()) {
            cout << "Stack Underflow! Cannot pop." << endl;
            return -1;  // Error value
        }
        int item = array[top];  // Get top item
        top--;                  // Move top pointer down
        cout << "Popped " << item << endl;
        return item;
    }
    
    // Peek (view top without removing)
    int peek() {
        if (isEmpty()) {
            cout << "Stack is empty!" << endl;
            return -1;
        }
        return array[top];
    }
};
