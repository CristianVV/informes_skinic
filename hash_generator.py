import streamlit_authenticator as stauth

# List of passwords to hash
passwords = ["Pr0cy0n2024!", "B3lv12024!"]
hashed_passwords = [stauth.Hasher([password]).hash(password) for password in passwords]

# Print the hashed passwords
for original, hashed in zip(passwords, hashed_passwords):
    print(f'Original: {original} -> Hashed: {hashed}')