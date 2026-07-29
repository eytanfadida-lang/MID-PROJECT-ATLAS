MAX_ATTEMPTS = 3


# אחראית על זרימת ההתחברות האינטראקטיבית ב-CLI: שם משתמש + סיסמה, עד MAX_ATTEMPTS ניסיונות
class LoginService:
    def __init__(self, user_repository):
        self.user_repository = user_repository

    # מריצה עד MAX_ATTEMPTS ניסיונות התחברות, ומחזירה {"username", "role"} בהצלחה או None בכישלון
    def login(self):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            username = input("Username: ")
            password = input("Password: ")

            role = self.user_repository.authenticate(username, password)
            if role is not None:
                print(f"Welcome, {username} (role: {role}).")
                return {"username": username, "role": role}

            print(f"Invalid username or password. ({attempt}/{MAX_ATTEMPTS})")

        print("Too many failed attempts. Exiting.")
        return None

