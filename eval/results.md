# Guardian classifier evaluation

Engine: `keywords` · 32 synthetic cases (English, Uzbek, Russian)

| Metric | Value |
|---|---|
| Unsafe-vs-safe precision | 100% |
| Unsafe-vs-safe recall | 100% |
| Exact category accuracy | 100% |
| False alarms on safe content | 0 / 10 |

| Expected | Predicted | Risk | OK | Text |
|---|---|---|---|---|
| GROOMING | GROOMING | 95 | ✅ | hey you're really good at this game, how old are you? this i |
| GROOMING | GROOMING | 90 | ✅ | i can give you 1000 robux if you send me a selfie first, del |
| GROOMING | GROOMING | 90 | ✅ | you're so mature for your age. add me on telegram, just us |
| GROOMING | GROOMING | 95 | ✅ | bu gaplarni hech kimga aytma, ota-onangga aytma, bu bizning  |
| GROOMING | GROOMING | 95 | ✅ | никому не говори, скинь фото, это наш секрет |
| GROOMING | GROOMING | 90 | ✅ | let's meet in person after school, don't tell anyone |
| PII | PII | 70 | ✅ | where do you live? which school do you go to? |
| PII | PII | 70 | ✅ | Chilonzor, 45-maktab, my number is +998 90 123 45 67 |
| PII | PII | 75 | ✅ | qayerda yashaysan? qaysi maktab? telefon raqamingni yoz |
| PII | PII | 70 | ✅ | send me your location and my password is sam2014 |
| BULLYING | BULLYING | 70 | ✅ | you're so ugly, nobody likes you |
| BULLYING | BULLYING | 70 | ✅ | everyone hates you, just leave the group loser |
| BULLYING | BULLYING | 70 | ✅ | sen ahmoqsan, seni hech kim yoqtirmaydi |
| BULLYING | BULLYING | 75 | ✅ | тупой урод, тебя все ненавидят |
| SELF_HARM | SELF_HARM | 85 | ✅ | i just want to die, nobody would even notice |
| SELF_HARM | SELF_HARM | 85 | ✅ | sometimes i want to hurt myself when things get bad |
| SCAM | SCAM | 70 | ✅ | FREE 10,000 ROBUX! enter your password to claim your prize |
| SCAM | SCAM | 80 | ✅ | you have won free v-bucks, verify your account and send the  |
| SCAM | SCAM | 70 | ✅ | free nitro giveaway, claim your reward now |
| GAMBLING | GAMBLING | 90 | ✅ | 1xbet live casino, place your bet now, jackpot bonus |
| GAMBLING | GAMBLING | 80 | ✅ | stake.com casino spin and win |
| VIOLENCE | VIOLENCE | 70 | ✅ | I'll stab you tomorrow at school |
| SAFE | SAFE | 5 | ✅ | How to add fractions with unlike denominators: find a common |
| SAFE | SAFE | 5 | ✅ | gg that was a great match, wanna play again tomorrow? |
| SAFE | SAFE | 5 | ✅ | Mom said dinner is at 7, can you bring the math book? |
| SAFE | SAFE | 5 | ✅ | Ertaga matematika uy vazifasini birga qilamizmi? |
| SAFE | SAFE | 5 | ✅ | Minecraft tutorial: how to build a redstone door |
| SAFE | SAFE | 5 | ✅ | The school library opens at 9 on Saturday |
| SAFE | SAFE | 5 | ✅ | lol that meme is so funny, send it to the group |
| SAFE | SAFE | 5 | ✅ | Happy birthday! Hope you have an amazing day |
| SAFE | SAFE | 5 | ✅ | bet, see you at practice |
| SAFE | SAFE | 5 | ✅ | Photosynthesis converts light energy into chemical energy |
