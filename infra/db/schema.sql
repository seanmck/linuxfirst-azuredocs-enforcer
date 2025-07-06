--
-- PostgreSQL database dump
--

-- Dumped from database version 15.13 (Debian 15.13-1.pgdg120+1)
-- Dumped by pg_dump version 16.9 (Ubuntu 16.9-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: pages; Type: TABLE; Schema: public; Owner: azuredocs_user
--

CREATE TABLE public.pages (
    id integer NOT NULL,
    scan_id integer,
    url character varying,
    status character varying
);


ALTER TABLE public.pages OWNER TO azuredocs_user;

--
-- Name: pages_id_seq; Type: SEQUENCE; Schema: public; Owner: azuredocs_user
--

CREATE SEQUENCE public.pages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.pages_id_seq OWNER TO azuredocs_user;

--
-- Name: pages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: azuredocs_user
--

ALTER SEQUENCE public.pages_id_seq OWNED BY public.pages.id;


--
-- Name: scans; Type: TABLE; Schema: public; Owner: azuredocs_user
--

CREATE TABLE public.scans (
    id integer NOT NULL,
    url character varying,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    status character varying,
    biased_pages_count integer,
    flagged_snippets_count integer
);


ALTER TABLE public.scans OWNER TO azuredocs_user;

--
-- Name: scans_id_seq; Type: SEQUENCE; Schema: public; Owner: azuredocs_user
--

CREATE SEQUENCE public.scans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.scans_id_seq OWNER TO azuredocs_user;

--
-- Name: scans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: azuredocs_user
--

ALTER SEQUENCE public.scans_id_seq OWNED BY public.scans.id;


--
-- Name: snippets; Type: TABLE; Schema: public; Owner: azuredocs_user
--

CREATE TABLE public.snippets (
    id integer NOT NULL,
    page_id integer,
    context text,
    code text,
    llm_score json
);


ALTER TABLE public.snippets OWNER TO azuredocs_user;

--
-- Name: snippets_id_seq; Type: SEQUENCE; Schema: public; Owner: azuredocs_user
--

CREATE SEQUENCE public.snippets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.snippets_id_seq OWNER TO azuredocs_user;

--
-- Name: snippets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: azuredocs_user
--

ALTER SEQUENCE public.snippets_id_seq OWNED BY public.snippets.id;


--
-- Name: pages id; Type: DEFAULT; Schema: public; Owner: azuredocs_user
--

ALTER TABLE ONLY public.pages ALTER COLUMN id SET DEFAULT nextval('public.pages_id_seq'::regclass);


--
-- Name: scans id; Type: DEFAULT; Schema: public; Owner: azuredocs_user
--

ALTER TABLE ONLY public.scans ALTER COLUMN id SET DEFAULT nextval('public.scans_id_seq'::regclass);


--
-- Name: snippets id; Type: DEFAULT; Schema: public; Owner: azuredocs_user
--

ALTER TABLE ONLY public.snippets ALTER COLUMN id SET DEFAULT nextval('public.snippets_id_seq'::regclass);


--
-- Name: pages pages_pkey; Type: CONSTRAINT; Schema: public; Owner: azuredocs_user
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT pages_pkey PRIMARY KEY (id);


--
-- Name: scans scans_pkey; Type: CONSTRAINT; Schema: public; Owner: azuredocs_user
--

ALTER TABLE ONLY public.scans
    ADD CONSTRAINT scans_pkey PRIMARY KEY (id);


--
-- Name: snippets snippets_pkey; Type: CONSTRAINT; Schema: public; Owner: azuredocs_user
--

ALTER TABLE ONLY public.snippets
    ADD CONSTRAINT snippets_pkey PRIMARY KEY (id);


--
-- Name: pages pages_scan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: azuredocs_user
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT pages_scan_id_fkey FOREIGN KEY (scan_id) REFERENCES public.scans(id);


--
-- Name: snippets snippets_page_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: azuredocs_user
--

ALTER TABLE ONLY public.snippets
    ADD CONSTRAINT snippets_page_id_fkey FOREIGN KEY (page_id) REFERENCES public.pages(id);


--
-- PostgreSQL database dump complete
--

