CREATE TABLE change (
	change_id VARCHAR(32) NOT NULL, 
	number VARCHAR(120) NOT NULL, 
	short_description VARCHAR(120) NOT NULL, 
	requested_by VARCHAR(32) NOT NULL, 
	service VARCHAR(32), 
	service_offering VARCHAR(32), 
	configuration_item VARCHAR(32), 
	assigned_to VARCHAR(32), 
	assignment_group VARCHAR(32), 
	org_id VARCHAR(32) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	category VARCHAR(50) NOT NULL, 
	description VARCHAR(120), 
	implementation_plan VARCHAR(120), 
	testing_plan VARCHAR(120), 
	close_notes VARCHAR(120), 
	cab_required BOOLEAN, 
	impact VARCHAR(20) NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	risk VARCHAR(20) NOT NULL, 
	close_code VARCHAR(50), 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (change_id), 
	FOREIGN KEY(requested_by) REFERENCES users (user_id), 
	FOREIGN KEY(service) REFERENCES service (service_id), 
	FOREIGN KEY(service_offering) REFERENCES service_offering (service_offering_id), 
	FOREIGN KEY(configuration_item) REFERENCES configuration_item (configuration_item_id), 
	FOREIGN KEY(assigned_to) REFERENCES users (user_id), 
	FOREIGN KEY(assignment_group) REFERENCES user_group (group_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE change_request_mapping (
	change_request_mapping_id VARCHAR(32) NOT NULL, 
	change_id VARCHAR(32) NOT NULL, 
	incident_id VARCHAR(32), 
	problem_id VARCHAR(32), 
	org_id VARCHAR(32) NOT NULL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (change_request_mapping_id), 
	CONSTRAINT ck_crm_incident_or_problem CHECK (incident_id IS NOT NULL OR problem_id IS NOT NULL), 
	CONSTRAINT uq_crm_change_incident UNIQUE (org_id, change_id, incident_id), 
	CONSTRAINT uq_crm_change_problem UNIQUE (org_id, change_id, problem_id), 
	FOREIGN KEY(change_id) REFERENCES change (change_id), 
	FOREIGN KEY(incident_id) REFERENCES incident (incident_id), 
	FOREIGN KEY(problem_id) REFERENCES problem (problem_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE child_incident (
	child_incident_mapping_id VARCHAR(32) NOT NULL, 
	parent_incident VARCHAR(32) NOT NULL, 
	child_incident VARCHAR(32) NOT NULL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (child_incident_mapping_id), 
	CONSTRAINT uq_parent_child_incident UNIQUE (parent_incident, child_incident), 
	CONSTRAINT ck_child_inc_not_self CHECK (parent_incident <> child_incident), 
	FOREIGN KEY(parent_incident) REFERENCES incident (incident_id), 
	FOREIGN KEY(child_incident) REFERENCES incident (incident_id)
);

CREATE TABLE configuration_item (
	configuration_item_id VARCHAR(32) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	serial_number VARCHAR(60) NOT NULL, 
	owner_id VARCHAR(32) NOT NULL, 
	location_id VARCHAR(32), 
	org_id VARCHAR(32) NOT NULL, 
	status VARCHAR(11) NOT NULL, 
	cost NUMERIC(10, 2), 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (configuration_item_id), 
	CONSTRAINT ck_ci_cost_positive CHECK (cost IS NULL OR cost >= 0), 
	FOREIGN KEY(owner_id) REFERENCES users (user_id), 
	FOREIGN KEY(location_id) REFERENCES location (location_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE incident (
	incident_id VARCHAR(32) NOT NULL, 
	number VARCHAR(120) NOT NULL, 
	short_description VARCHAR(120) NOT NULL, 
	caller_id VARCHAR(32) NOT NULL, 
	service VARCHAR(32), 
	service_offering VARCHAR(32), 
	configuration_item VARCHAR(32), 
	assigned_to VARCHAR(32), 
	assignment_group VARCHAR(32), 
	resolved_by VARCHAR(32), 
	problem VARCHAR(32), 
	change_request VARCHAR(32), 
	caused_by_change VARCHAR(32), 
	incident_template VARCHAR(32), 
	parent_incident VARCHAR(32), 
	org_id VARCHAR(32) NOT NULL, 
	channel VARCHAR(13), 
	contact_type VARCHAR(7), 
	status VARCHAR(11) NOT NULL, 
	category VARCHAR(14) NOT NULL, 
	description VARCHAR(120), 
	worknotes VARCHAR(120), 
	resolution_notes VARCHAR(120), 
	close_notes VARCHAR(120), 
	impact VARCHAR(6) NOT NULL, 
	urgency VARCHAR(6) NOT NULL, 
	priority VARCHAR(8) NOT NULL, 
	resolution_code VARCHAR(22), 
	on_hold_reason VARCHAR(16), 
	resolved DATETIME, 
	created_at DATETIME, 
	updated_at DATETIME, 
	service_display VARCHAR(255), 
	service_offering_display VARCHAR(255), 
	configuration_item_display VARCHAR(255), 
	assigned_to_display VARCHAR(255), 
	assignment_group_display VARCHAR(255), 
	parent_incident_display VARCHAR(255), 
	problem_display VARCHAR(255), 
	change_request_display VARCHAR(255), 
	incident_template_display VARCHAR(255), 
	PRIMARY KEY (incident_id), 
	FOREIGN KEY(caller_id) REFERENCES users (user_id), 
	FOREIGN KEY(service) REFERENCES service (service_id), 
	FOREIGN KEY(service_offering) REFERENCES service_offering (service_offering_id), 
	FOREIGN KEY(configuration_item) REFERENCES configuration_item (configuration_item_id), 
	FOREIGN KEY(assigned_to) REFERENCES users (user_id), 
	FOREIGN KEY(assignment_group) REFERENCES user_group (group_id), 
	FOREIGN KEY(resolved_by) REFERENCES users (user_id), 
	FOREIGN KEY(problem) REFERENCES problem (problem_id), 
	FOREIGN KEY(change_request) REFERENCES change (change_id), 
	FOREIGN KEY(caused_by_change) REFERENCES change (change_id), 
	FOREIGN KEY(incident_template) REFERENCES incident_template (incident_template_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE incident_affected_cis (
	incident_affected_cis_id VARCHAR(32) NOT NULL, 
	configuration_item VARCHAR(32) NOT NULL, 
	incident_id VARCHAR(32) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (incident_affected_cis_id), 
	CONSTRAINT uq_org_incident_ci UNIQUE (org_id, incident_id, configuration_item), 
	FOREIGN KEY(configuration_item) REFERENCES configuration_item (configuration_item_id), 
	FOREIGN KEY(incident_id) REFERENCES incident (incident_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE incident_knowledge (
	incident_kb_id VARCHAR(32) NOT NULL, 
	incident_id VARCHAR(32) NOT NULL, 
	knowledge_id VARCHAR(32) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	used_as VARCHAR(10) NOT NULL, 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (incident_kb_id), 
	CONSTRAINT uq_incident_knowledge_org UNIQUE (org_id, incident_id, knowledge_id), 
	FOREIGN KEY(incident_id) REFERENCES incident (incident_id), 
	FOREIGN KEY(knowledge_id) REFERENCES knowledge (knowledge_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE incident_sla (
	incident_sla_id VARCHAR(32) NOT NULL, 
	incident_id VARCHAR(32) NOT NULL, 
	sla_def_id VARCHAR(32) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	stage VARCHAR(11) NOT NULL, 
	has_breached BOOLEAN NOT NULL, 
	start_time DATETIME NOT NULL, 
	breach_time DATETIME, 
	completed_time DATETIME, 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (incident_sla_id), 
	CONSTRAINT uq_org_incident_sla_def UNIQUE (org_id, incident_id, sla_def_id), 
	CONSTRAINT ck_sla_breach_time CHECK (breach_time IS NULL OR start_time IS NULL OR breach_time >= start_time), 
	FOREIGN KEY(incident_id) REFERENCES incident (incident_id), 
	FOREIGN KEY(sla_def_id) REFERENCES sla_definition (sla_def_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE incident_template (
	incident_template_id VARCHAR(32) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	active BOOLEAN, 
	caller_id VARCHAR(32) NOT NULL, 
	channel VARCHAR(13), 
	short_description VARCHAR(120) NOT NULL, 
	category VARCHAR(14), 
	impact VARCHAR(6) NOT NULL, 
	urgency VARCHAR(6) NOT NULL, 
	priority VARCHAR(8) NOT NULL, 
	configuration_item VARCHAR(32), 
	service VARCHAR(32), 
	service_offering VARCHAR(32), 
	org_id VARCHAR(32) NOT NULL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (incident_template_id), 
	FOREIGN KEY(caller_id) REFERENCES users (user_id), 
	FOREIGN KEY(configuration_item) REFERENCES configuration_item (configuration_item_id), 
	FOREIGN KEY(service) REFERENCES service (service_id), 
	FOREIGN KEY(service_offering) REFERENCES service_offering (service_offering_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE knowledge (
	knowledge_id VARCHAR(32) NOT NULL, 
	kb_number VARCHAR(40) NOT NULL, 
	title VARCHAR(120) NOT NULL, 
	short_description VARCHAR(255), 
	body TEXT, 
	state VARCHAR(9) NOT NULL, 
	visibility VARCHAR(8) NOT NULL, 
	owner_id VARCHAR(32), 
	org_id VARCHAR(32) NOT NULL, 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (knowledge_id), 
	FOREIGN KEY(owner_id) REFERENCES users (user_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE location (
	location_id VARCHAR(32) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	plot_no VARCHAR(60), 
	street VARCHAR(60), 
	city VARCHAR(100) NOT NULL, 
	state VARCHAR(100), 
	country VARCHAR(100) NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (location_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE notification (
	notification_id VARCHAR(32) NOT NULL, 
	incident_id VARCHAR(32) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	email VARCHAR(120) NOT NULL, 
	subject VARCHAR(255), 
	message VARCHAR(2000), 
	type VARCHAR(17), 
	status VARCHAR(9), 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (notification_id), 
	CONSTRAINT ck_notification_email_format CHECK (email LIKE '%@%'), 
	FOREIGN KEY(incident_id) REFERENCES incident (incident_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE organization (
	org_id VARCHAR(32) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (org_id), 
	UNIQUE (name)
);

CREATE TABLE permission (
	perm_id VARCHAR(32) NOT NULL, 
	resource VARCHAR(50) NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	PRIMARY KEY (perm_id), 
	CONSTRAINT uq_perm_resource_action UNIQUE (resource, action)
);

CREATE TABLE problem (
	problem_id VARCHAR(32) NOT NULL, 
	number VARCHAR(120) NOT NULL, 
	problem_statement VARCHAR NOT NULL, 
	short_description VARCHAR(255), 
	opened_by VARCHAR(32) NOT NULL, 
	service VARCHAR(32), 
	service_offering VARCHAR(32), 
	configuration_item VARCHAR(32), 
	assigned_to VARCHAR(32), 
	assignment_group VARCHAR(32), 
	original_task VARCHAR(32), 
	org_id VARCHAR(32) NOT NULL, 
	status VARCHAR(15) NOT NULL, 
	category VARCHAR(8), 
	worknotes TEXT, 
	workaround TEXT, 
	fix_notes TEXT, 
	impact VARCHAR(6) NOT NULL, 
	urgency VARCHAR(6) NOT NULL, 
	priority VARCHAR(8) NOT NULL, 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (problem_id), 
	FOREIGN KEY(opened_by) REFERENCES users (user_id), 
	FOREIGN KEY(service) REFERENCES service (service_id), 
	FOREIGN KEY(service_offering) REFERENCES service_offering (service_offering_id), 
	FOREIGN KEY(configuration_item) REFERENCES configuration_item (configuration_item_id), 
	FOREIGN KEY(assigned_to) REFERENCES users (user_id), 
	FOREIGN KEY(assignment_group) REFERENCES user_group (group_id), 
	FOREIGN KEY(original_task) REFERENCES incident (incident_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE role (
	role_id VARCHAR(32) NOT NULL, 
	name VARCHAR(8) NOT NULL, 
	PRIMARY KEY (role_id), 
	UNIQUE (name)
);

CREATE TABLE role_permission (
	role_id VARCHAR(32) NOT NULL, 
	perm_id VARCHAR(32) NOT NULL, 
	PRIMARY KEY (role_id, perm_id), 
	FOREIGN KEY(role_id) REFERENCES role (role_id), 
	FOREIGN KEY(perm_id) REFERENCES permission (perm_id)
);

CREATE TABLE service (
	service_id VARCHAR(32) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	owned_by VARCHAR(32) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	used_for VARCHAR(11) NOT NULL, 
	status VARCHAR(18) NOT NULL, 
	service_classification VARCHAR(21) NOT NULL, 
	business_criticality VARCHAR(17) NOT NULL, 
	description VARCHAR(500), 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (service_id), 
	FOREIGN KEY(owned_by) REFERENCES users (user_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE service_offering (
	service_offering_id VARCHAR(32) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	short_description VARCHAR(120) NOT NULL, 
	owned_by VARCHAR(32) NOT NULL, 
	business_service VARCHAR(32) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	used_for VARCHAR(11) NOT NULL, 
	status VARCHAR(18) NOT NULL, 
	service_classification VARCHAR(21) NOT NULL, 
	business_criticality VARCHAR(17) NOT NULL, 
	description VARCHAR(500), 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (service_offering_id), 
	FOREIGN KEY(owned_by) REFERENCES users (user_id), 
	FOREIGN KEY(business_service) REFERENCES service (service_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE sla_definition (
	sla_def_id VARCHAR(32) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	metric VARCHAR(10) NOT NULL, 
	target_mins INTEGER NOT NULL, 
	pause_on_pending BOOLEAN NOT NULL, 
	applies_to_priority VARCHAR(8), 
	active BOOLEAN NOT NULL, 
	schedule VARCHAR(32), 
	org_id VARCHAR(32) NOT NULL, 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (sla_def_id), 
	CONSTRAINT uq_sla_definition_org_name UNIQUE (org_id, name), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE user_group (
	group_id VARCHAR(32) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	type VARCHAR(27) NOT NULL, 
	active BOOLEAN NOT NULL, 
	email VARCHAR(120), 
	description VARCHAR(255), 
	manager_id VARCHAR(32) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (group_id), 
	FOREIGN KEY(manager_id) REFERENCES users (user_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE user_group_member (
	member_id VARCHAR(32) NOT NULL, 
	group_id VARCHAR(32) NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (member_id), 
	CONSTRAINT uq_group_member_org UNIQUE (org_id, group_id, user_id), 
	FOREIGN KEY(group_id) REFERENCES user_group (group_id), 
	FOREIGN KEY(user_id) REFERENCES users (user_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE user_role (
	user_id VARCHAR(32) NOT NULL, 
	role_id VARCHAR(32) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	PRIMARY KEY (user_id, role_id, org_id), 
	CONSTRAINT uq_user_role_org UNIQUE (user_id, role_id, org_id), 
	FOREIGN KEY(user_id) REFERENCES users (user_id), 
	FOREIGN KEY(role_id) REFERENCES role (role_id), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);

CREATE TABLE users (
	user_id VARCHAR(32) NOT NULL, 
	user_name VARCHAR(100) NOT NULL, 
	first_name VARCHAR(60) NOT NULL, 
	last_name VARCHAR(60) NOT NULL, 
	email VARCHAR(120) NOT NULL, 
	phone VARCHAR(30) NOT NULL, 
	role VARCHAR(50) NOT NULL, 
	active BOOLEAN NOT NULL, 
	static_token VARCHAR(255) NOT NULL, 
	org_id VARCHAR(32) NOT NULL, 
	location_id VARCHAR(32), 
	created_on DATETIME, 
	updated_on DATETIME, 
	PRIMARY KEY (user_id), 
	CONSTRAINT ck_user_email_format CHECK (email LIKE '%@%'), 
	UNIQUE (phone), 
	FOREIGN KEY(role) REFERENCES role (name), 
	FOREIGN KEY(org_id) REFERENCES organization (org_id)
);
