
CREATE TABLE accounts (
	id VARCHAR(40) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	balance BIGINT NOT NULL, 
	frozen BOOL NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	timestamp VARCHAR(40) NOT NULL, 
	level VARCHAR(10) NOT NULL, 
	service VARCHAR(40) NOT NULL, 
	trace_id VARCHAR(32) NOT NULL, 
	span_id VARCHAR(16) NOT NULL, 
	transaction_id VARCHAR(40) NOT NULL, 
	event VARCHAR(80) NOT NULL, 
	message LONGTEXT NOT NULL, 
	duration_ms INTEGER NOT NULL, 
	status INTEGER NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_logs_timestamp ON logs (timestamp);
CREATE INDEX ix_logs_transaction_id ON logs (transaction_id);
CREATE INDEX ix_logs_trace_id ON logs (trace_id);

CREATE TABLE faults (
	id VARCHAR(40) NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	started_at VARCHAR(40) NOT NULL, 
	expires_at VARCHAR(40) NOT NULL, 
	stopped_at VARCHAR(40), 
	delay_ms INTEGER NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE documents (
	id VARCHAR(40) NOT NULL, 
	title VARCHAR(120) NOT NULL, 
	version VARCHAR(40) NOT NULL, 
	service VARCHAR(40) NOT NULL, 
	content LONGTEXT NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE chat_turns (
	id VARCHAR(40) NOT NULL, 
	session_id VARCHAR(40) NOT NULL, 
	question LONGTEXT NOT NULL, 
	answer LONGTEXT NOT NULL, 
	citations LONGTEXT NOT NULL, 
	mode VARCHAR(40) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_chat_turns_session_id ON chat_turns (session_id);

CREATE TABLE trades (
	id VARCHAR(40) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	source_id VARCHAR(40) NOT NULL, 
	target_id VARCHAR(40) NOT NULL, 
	amount BIGINT NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	error_code VARCHAR(50) NOT NULL, 
	original_id VARCHAR(40), 
	refunded BIGINT NOT NULL, 
	trace_id VARCHAR(32) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (idempotency_key), 
	FOREIGN KEY(source_id) REFERENCES accounts (id), 
	FOREIGN KEY(target_id) REFERENCES accounts (id), 
	FOREIGN KEY(original_id) REFERENCES trades (id)
)

;
CREATE INDEX ix_trades_created_at ON trades (created_at);

CREATE TABLE chunks (
	id VARCHAR(50) NOT NULL, 
	document_id VARCHAR(40) NOT NULL, 
	position INTEGER NOT NULL, 
	text LONGTEXT NOT NULL, 
	embedding LONGTEXT, 
	embedding_model VARCHAR(120) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id)
)

;
CREATE INDEX ix_chunks_document_id ON chunks (document_id);

CREATE TABLE entries (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	trade_id VARCHAR(40) NOT NULL, 
	account_id VARCHAR(40) NOT NULL, 
	side VARCHAR(10) NOT NULL, 
	delta BIGINT NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(trade_id) REFERENCES trades (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
)

;
CREATE INDEX ix_entries_trade_id ON entries (trade_id);
CREATE INDEX ix_entries_account_id ON entries (account_id);
