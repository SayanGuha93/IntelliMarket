from main import run_tracker
import subprocess

def menu():
    while True:
        print("\n--- PRICE TRACKER SYSTEM ---")
        print("1. Collect Price Data")
        print("2. Analyze Data (Graph + Stats)")
        print("3. Exit")

        choice = input("Enter choice: ")

        if choice == "1":
            run_tracker()
        elif choice == "2":
            subprocess.run(["python", "analysis.py"])
        elif choice == "3":
            break
        else:
            print("Invalid choice")

if __name__ == "__main__":
    menu()