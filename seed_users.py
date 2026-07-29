import sqlite3

from user_db import UserDB
from user_repository import UserRepository
import roles

# סקריפט חד-פעמי (מריצים ידנית, לא חלק מהאפליקציה) ליצירת חשבון admin ולאחריו
# כמה שמשתמשים רגילים שרוצים, לפני ההרצה הראשונה של rest_app.py


def _prompt_new_user(role):
    username = input("Username: ")
    password = input("Password: ")
    return username, password, role


def _create_user(user_repository, username, password, role):
    try:
        user_repository.create(username, password, role)
        print(f"User '{username}' created successfully (role: {role}).")
    except sqlite3.IntegrityError:
        print(f"Username '{username}' already exists, skipped.")


def main():
    db = UserDB()
    user_repository = UserRepository(db.conn)

    print("Create the admin account:")
    _create_user(user_repository, *_prompt_new_user(roles.ADMIN))

    print("\nNow create the regular user accounts (leave the username empty to stop):")
    while True:
        username = input("Username (empty to finish): ")
        if not username:
            break
        password = input("Password: ")
        _create_user(user_repository, username, password, roles.USER)

    db.close()


if __name__ == "__main__":
    main()
