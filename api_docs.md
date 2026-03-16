## Elements360 API Documentation

This document describes the primary backend APIs used by the Elements360 Flutter app.

---

## Enrolment

### Enrolment Departments API

- **Purpose**: Returns the list of enrolment departments for staff (e.g. Front of House).
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/enrolment/departments`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**: _none_
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (department)**:
    - `id` (number)
    - `name` (string)

### Get All Enrolments API

- **Purpose**: Returns all staff enrolment records, including detailed enrolment data per staff (used e.g. for iPad clock-in staff selection).
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/enrolment/getAllEnrolments`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**: _none_
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (staff enrolment)**:
    - `id`
    - `staff` (embedded staff object; id, firstName, lastName, etc.)
    - personal, banking, tax and visa/compliance fields
    - `staffDepartment`
    - document lists (e.g. `personalPhotoFiles`, `australianPassportDocuments`, etc.)

### Enrolment All Staffs API

- **Purpose**: Returns a list of all enrolled staff members (used for training and other features).
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/enrolment/staffs`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**: _none_
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (staff mini)**:
    - `id`
    - `firstName`
    - `lastName`
    - `email` (optional)
    - `phoneNumber` (optional)
    - `terminated` (boolean)

### Enrolment Staffs by Department API

- **Purpose**: Returns staff list filtered by a specific department.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/enrolment/staffsByDepartment?departmentId={departmentId}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `departmentId` (number, required)
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape**: same as **Enrolment All Staffs API**.

---

## Clocking

### Clocking Sites API

- **Purpose**: Returns all clocking sites used for staff clock-in/clock-out, including geolocation and radius.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/clocking/sites`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**: _none_
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (site)**:
    - `id`
    - `site`
    - `latitude`
    - `longitude`
    - `radius`
    - (other site metadata as defined in the `Site` model)

### Clocking Paginated Records API

- **Purpose**: Returns paginated clocking records for a specific staff member, grouped by week.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/clocking/record/paginated?staffId={staffId}&page={page}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `staffId` (number, required)
    - `page` (number, required; 1-based)
- **Response Structure**:
  - **Top-level**: JSON array of `ClockingRecordsByWeek`
  - **Important field paths**:
    - `[i].weekStartDate`
    - `[i].weekEndDate`
    - `[i].clockingRecords` (array of clock-in records)
      - `[i].clockingRecords[j].id`
      - `[i].clockingRecords[j].clockInDate`
      - `[i].clockingRecords[j].clockInTime`
      - `[i].clockingRecords[j].clockOutTime`
      - `[i].clockingRecords[j].workDuration`

### Clocking Check Status API

- **Purpose**: Returns current clock-in status for a staff member (whether clock-in is running, and basic details).
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/clocking/record/checkClockingStatus?staffId={staffId}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `staffId` (number, required)
- **Response Structure**:
  - **Top-level**: flat JSON object
  - **Important field paths**:
    - `RESPONSE` (string; `"CLOCK_IN_NOT_RUNNING"` or other)
    - `CLOCKING_RECORD_ID` (number)
    - `WORK_DURATION` (string, format `HH:mm`)
    - `CLOCK_IN_TIME` (string, e.g. `10:30 AM`)
    - `CLOCK_IN_DATE` (string, `yyyy-MM-dd`)

---

## Checklist

### Checklist Venues API

- **Purpose**: Returns the list of venues for which checklists can be created.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/checklist/venues`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**: _none_
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (venue)**:
    - `id`
    - `venueName`
    - `venueInitial`
    - `site`

### Checklist Types API

- **Purpose**: Returns all available checklist types (e.g. FOH/BOH opening, closing).
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/checklist/type/all`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**: _none_
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (checklist type)**:
    - `id`
    - `type` (string, e.g. `"BOH Opening Checklist"`)
    - `hasGroups` (boolean)

### Checklist Record API

- **Purpose**: Returns a checklist record for a given date, type, and venue if it exists.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/checklist/record?date={date}&typeId={typeId}&venueId={venueId}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `date` (string, `yyyy-MM-dd`, required)
    - `typeId` (number, required)
    - `venueId` (number, required)
- **Response Structure**:
  - **Top-level**:
    - `RESPONSE` (string)
      - `"CHECKLIST_RECORD_FOUND"` if a record exists
      - other value if not found
    - `RECORD` (object) — only present when a record exists
  - **Important field paths (`RECORD`)**:
    - `id`
    - `date`
    - `checklistType.id`
    - `checklistType.type`
    - `elementsVenue.id`
    - `elementsVenue.venueName`
    - `submitted` (boolean)
    - `checklistReadings` (array)
      - `checklistReadings[i].id`
      - `checklistReadings[i].checked` (bool)
      - `checklistReadings[i].comment` (string or null)
      - `checklistReadings[i].checklistCriteria.id`
      - `checklistReadings[i].checklistCriteria.name`
      - `checklistReadings[i].checklistCriteria.checklistType.id`

### Checklist Criteria by Type API

- **Purpose**: Returns all checklist criteria for a particular checklist type.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/checklist/criteria/type?typeId={typeId}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `typeId` (number, required)
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (checklist criteria)**:
    - `id`
    - `name` (string)
    - `sn` (sequence number)
    - `checklistType.id`
    - `checklistType.type`
    - `checklistGroup` (optional)
      - `checklistGroup.id`
      - `checklistGroup.name`

---

## TempLog

### TempLog Record API

- **Purpose**: Returns temperature log record for a given venue and date, or a not-found response.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/templog/record?date={date}&venueId={venueId}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `date` (string, `yyyy-MM-dd`, required)
    - `venueId` (number, required)
- **Response Structure**:
  - **Top-level**:
    - `RESPONSE` (string)
      - `"TEMP_LOG_RECORD_NOT_FOUND"` if none
      - other values if found
    - `RECORD` (object) — only when exists
  - **Important field paths (`RECORD`)**:
    - `id`
    - `date`
    - `elementsVenue.id`
    - `elementsVenue.venueName`
    - `submitted` (boolean)
    - `submittedBy.id`
    - `tempLogReadings` (array)
      - `tempLogReadings[i].id`
      - `tempLogReadings[i].recordedValue` (number or null)
      - `tempLogReadings[i].acceptable` (boolean or null)
      - `tempLogReadings[i].na` (boolean)
      - `tempLogReadings[i].comment`
      - `tempLogReadings[i].tempLogCriteria.id`
      - `tempLogReadings[i].tempLogCriteria.name`
      - `tempLogReadings[i].tempLogCriteria.unitCode`
      - `tempLogReadings[i].tempLogCriteria.acceptableLowerValue`
      - `tempLogReadings[i].tempLogCriteria.acceptableUpperValue`
      - `tempLogReadings[i].tempLogCriteria.unit` (`"DEG_CEL"` or `"PERCENT"`)
      - `tempLogReadings[i].tempLogCriteria.tempLogGroup.name`

### TempLog Criteria by Venue API

- **Purpose**: Returns the list of temperature log criteria configured for a given venue.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/templog/criteria/venue?venueId={venueId}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `venueId` (number, required)
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (templog criteria)**:
    - `id`
    - `unitCode` (string)
    - `name` (string/description)
    - `acceptableLowerValue` (number)
    - `acceptableUpperValue` (number)
    - `unit` (`"DEG_CEL"` or `"PERCENT"`)
    - `tempLogGroup.id`
    - `tempLogGroup.name`

---

## Audit

### Audit Record API

- **Purpose**: Returns an audit record (internal or short audit) for a given date, venue, and audit type.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/audit/record?date={date}&venueId={venueId}&auditTypeId={auditTypeId}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `date` (string, `yyyy-MM-dd`, required)
    - `venueId` (number, required)
    - `auditTypeId` (number, required)
- **Response Structure**:
  - **Top-level**:
    - `RESPONSE` (string)
      - `"AUDIT_RECORD_FOUND"` if a record exists
      - other value if not found
    - `RECORD` (object) — only when exists
  - **Important field paths (`RECORD`)**:
    - `id`
    - `date`
    - `elementsVenue.id`
    - `elementsVenue.venueName`
    - `auditType.id`
    - `auditType.name`
    - `submitted` (boolean)
    - `auditor.id`
    - `totalScore` (number)
    - `scorePercentage` (number)
    - `auditPassed` (boolean)
    - `auditReadings` (array)
      - `auditReadings[i].id`
      - `auditReadings[i].checked` (bool or null)
      - `auditReadings[i].na` (bool or null)
      - `auditReadings[i].comment`
      - `auditReadings[i].auditCriteria.id`
      - `auditReadings[i].auditCriteria.name`
      - `auditReadings[i].auditCriteria.sn`
      - `auditReadings[i].auditCriteria.critical` (boolean)
      - `auditReadings[i].auditCriteria.allocatedPoint` (number)
      - `auditReadings[i].auditCriteria.auditGroup.id`
      - `auditReadings[i].auditCriteria.auditGroup.name`
      - `auditReadings[i].auditCriteria.auditGroup.sn`
      - `auditReadings[i].auditReadingAttachedFiles` (optional array)
        - `...[j].id`
        - `...[j].url`

### Audit Types API

- **Purpose**: Returns all audit types (e.g. internal audit, short audit) available in the system.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/audit/auditType/all`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**: _none_
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (audit type)**:
    - `id`
    - `name`

### Audit Criteria API

- **Purpose**: Returns all audit criteria for a specific audit type.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/audit/criteria/all?auditTypeId={auditTypeId}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `auditTypeId` (number, required)
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (audit criteria)**:
    - `id`
    - `name`
    - `sn` (sequence number)
    - `allocatedPoint` (number)
    - `critical` (boolean)
    - `auditGroup.id`
    - `auditGroup.name`
    - `auditGroup.sn`

---

## Training

### Training Criteria List API

- **Purpose**: Returns all training criteria linked to a specific training subject.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/training/trainingCriteriaList?trainingSubjectId={trainingSubjectId}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `trainingSubjectId` (number, required)
- **Response Structure**:
  - **Top-level**: JSON array
  - **Element shape (training criteria)**:
    - `id`
    - `name` (string)
    - `sn` (sequence/order index)
    - (other training-specific fields as defined in `TrainingCriteria`)

### Training Subject API

- **Purpose**: Returns a single training subject configuration for a given station and training type.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/e360/training/trainingSubject?stationId={stationId}&trainingType={trainingType}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `stationId` (number, required)
    - `trainingType` (string, required; e.g. `"INITIAL_TRAINING"`, `"TRAINING_VERIFICATION"`)
- **Response Structure**:
  - **Top-level**: object (training subject)
  - **Important field paths**:
    - `id`
    - `name`
    - `trainingStation.id`
    - `trainingStation.name`
    - `trainingType`

---

## Breakage Reports

### Breakage Report by Venue and Date API

- **Purpose**: Returns a glassware breakage report for a specific venue and date, if it exists.
- **Endpoint**:
  - **Method**: GET
  - **URL**: `{BASE_URL}/api/breakageReport/reportByVenueAndDate?date={date}&venue={venue}`
- **Payload/Headers**:
  - **Content-Type**: `application/json`
  - **Query params**:
    - `date` (string, `yyyy-MM-dd`, required)
    - `venue` (string, required; venue identifier/name used by backend)
- **Response Structure**:
  - **Top-level**:
    - `RESPONSE` (string)
      - `"REPORT_EXISTS"` if a report exists
      - other value otherwise
    - `REPORT` (object) — only when exists
  - **Important field paths (`REPORT`)**:
    - `venue` (string)
    - `date` (string, `yyyy-MM-dd`)
    - `day` (string, e.g. `"Monday"`)
    - `submittedByStaff.id`
    - `totalBreakageCost` (number)
    - `netSales` (number)
    - `totalBreakagePercentage` (number; `totalBreakageCost / netSales`)
    - `finalized` (boolean)
    - `breakageDetails` (array)
      - `breakageDetails[i].id`
      - `breakageDetails[i].qty` (number)
      - `breakageDetails[i].reason` (string)
      - `breakageDetails[i].totalCost` (number)
      - `breakageDetails[i].glasswareItem.id`
      - `breakageDetails[i].glasswareItem.name`
      - `breakageDetails[i].glasswareItem.type`
      - `breakageDetails[i].glasswareItem.unitCost`

