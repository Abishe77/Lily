



/* 
This users table stores unique id for each users , then their name NOT NULL mean that name cannot
be empty it is mandatory , year_of_birth can be NULL that is thats not madatory , created_at stores
at which time and date the id is created 
*/
CREATE TABLE users( id SERIAL PRIMARY KEY , name VARCHAR(50) NOT NULL , year_of_birth SMALLINT , created_at TIMESTAMPTZ DEFAULT NOW());
/*
This style_profile table stores the style for each id created for it uses foreign key to access
the id from users and since we dont know the sample text  (The notes of the user) size like how
many words it has so we keep set it as dynamic by keeping as TEXT and style description too 
because we don't know what we will get in return 
*/
CREATE TABLE style_profiles(id SERIAL PRIMARY KEY , user_id INT REFERENCES users(id) NOT N ,sample_notes_txt TEXT NOT NULL, style_description TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW());
/*
This is source table a separate ones for each sources because sources is dynamic the user will
upload n number of sources so we need smth to store smth of that huge and retrieve it when
user asks for notes from specific topic from a specific source
*/
CREATE TABLE sources(id SERIAL PRIMARY KEY , user_id INT REFERENCES users(id), filename TEXT NOT NULL, extracted_text TEXT NOT NULL,uploaded_at TIMESTAMPTZ DEFAULT NOW());
/*
A seperate table that stores notes after generation this is where RAG becomes useful and this is
an important table since it helps to combine the style_profiles and sources tables
*/
CREATE TABLE notes(id SERIAL PRIMARY KEY, user_id INT REFERENCES users(id) ,source_id INT REFERENCES sources(id) , style_profile_id INT REFERENCES style_profiles(id), generated_text TEXT NOT NULL ,created_at TIMESTAMPTZ DEFAULT NOW());
/*
This is somekind of useful table because now our previous table stores the generated text
now imagine the whole chunk is from various different topics so sometimes we don't know 
what topic is this generated text is so what we do is make the whole generated chunk into
smaller pieces and cite them like from which source by linking them and order them like
consider you have three diff parts (heart , lungs , brain) and source has heart first 
then lungs then brain so we need to order the chunks too so heart[1] from source like page
number , then lungs[2] page number , brain[3] page number and imp distinction is each document
uploaded gets a fresh ordered index from one to N 
*/
CREATE TABLE note_blocks(id SERIAL PRIMARY KEY, note_id INT REFERENCES notes(id), content TEXT ,source_page INT NOT NULL , order_index INT NOT NULL);
/*
Creating a quiz table just to make the user engaged the quiz also will be in their style
now here is smth new JSON which is something like a object returned by our Claude instead
of plain text the object is either a single dictionary with keys or a array with dictionary
inside of it array feels easy to iterate and during our prompting use Claude API we specify 
the type of JSON object to return so that it can be accepted so visually looks like
{} : {
  "question1": {"question": "...", "options": [...], "answer": "..."},
  "question2": {"question": "...", "options": [...], "answer": "..."}
}
[] : [
  {"question": "...", "options": [...], "answer": "..."},
  {"question": "...", "options": [...], "answer": "..."}
]
we better use [] here 
*/
CREATE TABLE quizzes(id SERIAL PRIMARY KEY, note_id INT REFERENCES notes(id), questions_json JSONB NOT NULL DEFAULT '[]' :: jsonb, created_at TIMESTAMPTZ DEFAULT NOW());
/* A table to track process of quiz score and things like that
*/
CREATE TABLE quiz_attempts(id SERIAL PRIMARY KEY, quiz_id INT REFERENCES quizzes(id), user_id INT REFERENCES users(id), score INT NOT NULL, time_taken_seconds DECIMAL, attempted_at TIMESTAMPTZ DEFAULT NOW());

/*Altering the users table because we found a lot*/

ALTER TABLE users ADD COLUMN email VARCHAR(60) UNIQUE NOT NULL;
ALTER TABLE users ADD COLUMN hashed_pass VARCHAR(60) NOT NULL;

/* The friend table that clings with the user throughout the app*/

CREATE TABLE companions(id SERIAL PRIMARY KEY , user_id  INT UNIQUE REFERENCES users(id), name VARCHAR(20)NOT NULL, gender VARCHAR(7) NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW());
/* Now creating a weak study plan table it is condition and score based filtering
like if latest_score on quiz is >=7 it is not weak topic anymore , if 4-6 needs to be monitored
if below 4 then its urgent */

CREATE TYPE topic_status AS ENUM ('urgent', 'monitor', 'resolved');

CREATE TABLE weak_topics(id SERIAL PRIMARY KEY, user_id INT REFERENCES users(id), note_block_id INT REFERENCES note_blocks(id), latest_score INT ,status topic_status NOT NULL, next_review TIMESTAMPTZ , updated_at TIMESTAMPTZ DEFAULT NOW());

ALTER TABLE style_profiles ADD CONSTRAINT unique_user_style UNIQUE (user_id);

/*Testing the flow*/

INSERT INTO users (name , year_of_birth ,email ,hashed_pass)
VALUES('Olincy Helena', 2006, 'olincy@example.com', 'placeholderhash123456789');

SELECT * from users;

INSERT INTO companions(user_id ,name , gender)
VALUES(1 , 'Naga Abishe Kumar' , 'Male')

SELECT * from companions

INSERT INTO sources(user_id ,filename ,extracted_text)
VALUES(1,'Lily_SRS','This is abi hiiiii');

SELECT * from sources

INSERT INTO style_profiles(user_id,sample_notes_txt , style_description)
VALUES(1, 'Pumping lemma is used to prove a language is not regular', 'Intuition first formalism next');

SELECT * from style_profiles

INSERT INTO notes(user_id, source_id, style_profile_id, generated_text)
VALUES(1)

ALTER TABLE style_profiles ALTER COLUMN style_description DROP NOT NULL;

ALTER TABLE style_profiles ALTER COLUMN style_description SET NOT NULL;

ALTER TABLE style_profiles ALTER COLUMN sample_notes_txt DROP NOT NULL;

SELECT column_name, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'style_profiles';

DELETE FROM style_profiles WHERE user_id = 5;

SELECT * from style_profiles;

SELECT * from notes;

SELECT * from users;

SELECT * from sources;
DELETE FROM users where id = 6;

SELECT
    id,
    user_id,
    sample_notes_txt,
    style_description,
    LENGTH(style_description) AS characters,
    created_at
FROM style_profiles
WHERE user_id = 7
ORDER BY id DESC;

SELECT id, user_id, filename
FROM sources
ORDER BY id DESC;

SELECT id, filename, LENGTH(extracted_text)
FROM sources
ORDER BY id DESC
LIMIT 5;



SELECT * from users;

SELECT * from style_profiles;

SELECT * from sources;

SELECT * from notes;