# pyrefly: ignore [missing-import]
import customtkinter as ctk
import threading
import ollama
from ai import messages, MODEL, LISTE_FONCTIONS, outils_disponibles, faire_parler, ecouter

ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Alyx - Assistant Système")
        self.geometry("700x800")
        
        self.mode_vocal = False
        self.listening = False
        
        # Configuration des colonnes/lignes
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Historique de chat
        self.chat_history = ctk.CTkTextbox(self, state="disabled", font=("Helvetica", 14), wrap="word")
        self.chat_history.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="nsew")
        
        # Frame pour l'input
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.grid(row=1, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)
        
        self.entry = ctk.CTkEntry(self.input_frame, placeholder_text="Tape ton message ici...", font=("Helvetica", 14))
        self.entry.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="ew")
        self.entry.bind("<Return>", self.send_message)
        
        self.send_btn = ctk.CTkButton(self.input_frame, text="Envoyer", command=self.send_message, width=80)
        self.send_btn.grid(row=0, column=1, padx=5, pady=10)
        
        self.vocal_btn = ctk.CTkButton(self.input_frame, text="🎤 Off", command=self.toggle_vocal, width=60, fg_color="gray")
        self.vocal_btn.grid(row=0, column=2, padx=(5, 10), pady=10)
        
        self.append_to_chat("Système", "Alyx (Local via Ollama): Bonjour Maître Christ, l'Agent Système est en ligne.")
        
    def toggle_vocal(self):
        self.mode_vocal = not self.mode_vocal
        if self.mode_vocal:
            self.vocal_btn.configure(text="🎤 On", fg_color="#C850C0") # Couleur activée
            self.append_to_chat("Système", "Mode vocal activé. Je t'écoute...")
            self.listening = True
            threading.Thread(target=self.vocal_loop, daemon=True).start()
        else:
            self.vocal_btn.configure(text="🎤 Off", fg_color="gray")
            self.append_to_chat("Système", "Mode vocal désactivé.")
            self.listening = False
            
    def vocal_loop(self):
        while self.listening:
            user_input = ecouter()
            if user_input and self.listening:
                # Transférer l'input vocal à l'interface
                self.after(0, self.process_vocal_input, user_input)

    def process_vocal_input(self, text):
        self.append_to_chat("Vous (Vocal)", text)
        self.process_text_input(text)

    def append_to_chat(self, sender, message):
        self.chat_history.configure(state="normal")
        self.chat_history.insert("end", f"{sender}: {message}\n\n")
        self.chat_history.configure(state="disabled")
        self.chat_history.yview("end")
        
    def send_message(self, event=None):
        user_input = self.entry.get().strip()
        if not user_input:
            return
            
        self.entry.delete(0, "end")
        self.append_to_chat("Vous", user_input)
        self.process_text_input(user_input)
        
    def process_text_input(self, user_input):
        if user_input.lower() in ['bye', 'out', 'tu peux disposer']:
            self.append_to_chat("Alyx", "Déconnexion locale. À bientôt !")
            if self.mode_vocal:
                threading.Thread(target=faire_parler, args=("Déconnexion de l'Agent. À bientôt.",), daemon=True).start()
            self.after(2000, self.destroy)
            return
            
        messages.append({'role': 'user', 'content': user_input})
        
        # Bloquer le bouton d'envoi le temps que l'IA réfléchisse
        self.send_btn.configure(state="disabled", text="...")
        
        # Lancer la génération dans un thread
        threading.Thread(target=self.process_ai, daemon=True).start()
        
    def process_ai(self):
        try:
            response = ollama.chat(
                model=MODEL,
                messages=messages,
                tools=LISTE_FONCTIONS,
                keep_alive='1h'
            )
            message_ia = response['message']
            messages.append(message_ia)

            if message_ia.get('tool_calls'):
                for tool_call in message_ia['tool_calls']:
                    nom_fonction = tool_call['function']['name']
                    arguments = tool_call['function'].get('arguments', {})
                    
                    self.after(0, self.append_to_chat, "Système", f"[Action système détectée : exécution de {nom_fonction}({arguments})...]")

                    if nom_fonction in outils_disponibles:
                        try:
                            resultat_execution = outils_disponibles[nom_fonction](**arguments)
                        except TypeError:
                            resultat_execution = outils_disponibles[nom_fonction]()
                    else:
                        resultat_execution = f"Erreur: Outil {nom_fonction} introuvable."

                    messages.append({
                        'role': 'tool',
                        'content': resultat_execution,
                        'name': nom_fonction
                    })

                # Obtenir la réponse finale après avoir appelé l'outil
                response = ollama.chat(model=MODEL, messages=messages)
                message_ia = response['message']
                messages.append(message_ia)

            # Mettre à jour l'UI dans le thread principal
            self.after(0, self.finalize_ai_response, message_ia['content'])
            
            # Faire parler l'IA si mode vocal
            if self.mode_vocal:
                threading.Thread(target=faire_parler, args=(message_ia['content'],), daemon=True).start()

        except Exception as e:
            self.after(0, self.append_to_chat, "Erreur", f"Erreur système Ollama : {e}")
            self.after(0, self.send_btn.configure, {"state": "normal", "text": "Envoyer"})
            
    def finalize_ai_response(self, text):
        self.append_to_chat("Alyx", text)
        self.send_btn.configure(state="normal", text="Envoyer")

if __name__ == "__main__":
    app = App()
    app.mainloop()
