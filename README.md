# Smartphone Database Platform

## Introduction

This is a database-driven platform for smartphone recommendations, analytics, and natural-language queries, built for CIS 761 (DBMS). The application domain is smartphone data — device specifications, prices, release information, hardware features, connectivity, and brand-related characteristics — collected from public sources and organized into a structured relational database.

The full proposal and E-R diagram are in `Project_Proposal.pdf`.

## Use Cases

1. **Phone Recommendation.** Users specify preferences such as budget, preferred brand, operating system, RAM, storage capacity, battery size, display size, camera-related features, and 5G support. The application queries the database and returns the phones that best match the user's needs, turning the database into a personalized decision-support tool.

2. **Smartphone Market Analytics.** Users analyze the collected data and generate reports about trends in the smartphone market — average prices by brand, relationships between price and hardware specifications, battery-capacity trends, storage and RAM distributions, chipset popularity, and year-over-year changes in device features. This use case exercises SQL's strength in aggregation, filtering, grouping, ranking, and reporting.

3. **Natural-Language Query Interface.** Users ask questions in plain English instead of writing SQL. An SLM/LLM interprets the request, translates it into SQL against the smartphone database, executes the query, and presents results in a readable form (e.g. "phones under €500 with at least 128 GB and a 5000 mAh battery", or "brands with the best average value in 2023"). This keeps the relational database as the core engine while making it accessible to non-technical users.

## Project Steps

1. **Data Collection.** Gather smartphone data from public sources covering specifications and prices across a wide range of devices.
2. **Database Design.** Design and implement a normalized relational schema to store the data efficiently, with lookup tables for shared attributes and a central `Device` fact table. The E-R diagram is in `Project_Proposal.pdf`.
3. **Recommendation Engine.** Build the query layer that maps user preferences to SQL filters and ranks matching devices.
4. **Analytics & Reporting.** Implement the SQL analyses behind the market-analytics use case and present results in dashboards/reports.
5. **Natural-Language Interface.** Integrate an SLM/LLM that translates English questions into SQL and renders results for end users.

## Contributors

- [Sanaz Gheibuni](https://github.com/sanaazz)